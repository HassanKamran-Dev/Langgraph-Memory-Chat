from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage
from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from langgraph.store.base import BaseStore
from psycopg_pool import AsyncConnectionPool
import os
import json
from dotenv import load_dotenv
import rag_service

load_dotenv()


class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool
def search_uploaded_documents(query: str, config: RunnableConfig) -> str:
    """Search uploaded PDF documents in the current conversation for relevant excerpts and answers.
    Always call this tool whenever the user asks about an uploaded document, a PDF file, or questions
    that require information from their files.
    """
    thread_id = config.get("configurable", {}).get("thread_id", "default-thread")
    results = rag_service.search_documents(query, thread_id=thread_id, top_k=4)
    if not results:
        return (
            "No relevant excerpts found in the uploaded documents. "
            "If no documents have been uploaded yet, let the user know they can upload a PDF using the attachment button."
        )

    formatted = []
    for idx, r in enumerate(results, 1):
        formatted.append(
            f"--- Excerpt {idx} (Document: {r['source']} | Page: {r['page']}) ---\n{r['text']}"
        )
    return "\n\n".join(formatted)


@tool
def list_uploaded_documents(config: RunnableConfig) -> str:
    """List the names, page counts, and chunk counts of documents uploaded in this conversation."""
    thread_id = config.get("configurable", {}).get("thread_id", "default-thread")
    docs = rag_service.get_documents(thread_id=thread_id)
    if not docs:
        return "No documents have been uploaded in this conversation yet."

    lines = [f"- {d['filename']} ({d.get('pages', 1)} pages, {d.get('chunks', 0)} chunks)" for d in docs]
    return "Uploaded documents:\n" + "\n".join(lines)


tools = [search_uploaded_documents, list_uploaded_documents]

# ---------------------------------------------------------------------------
# LLMs
# ---------------------------------------------------------------------------

llm = ChatGroq(
    model="openai/gpt-oss-120b",  # Supports function calling & reasoning
    temperature=0.7,
    streaming=True
)

llm_with_tools = llm.bind_tools(tools)

# Separate LLM for memory extraction (no tools, deterministic)
memory_llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0,
    streaming=False
)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a helpful, knowledgeable, and concise conversational AI assistant. "
    "You have access to tools `search_uploaded_documents` and `list_uploaded_documents` to query files uploaded by the user. "
    "Whenever the user asks questions about their uploaded documents, PDFs, or files, always invoke `search_uploaded_documents` "
    "to retrieve accurate information. "
    "When answering based on retrieved documents, always cite the document name and page number (e.g. '[Document: filename.pdf, Page X]'). "
    "If no relevant documents are found or uploaded, let the user know they can upload PDF files using the attachment icon."
)

MEMORY_EXTRACTION_PROMPT = (
    "You are a memory extraction assistant. Analyze the conversation below and "
    "extract any NEW personal facts the user has explicitly shared about themselves.\n\n"
    "Output ONLY a valid JSON array. Each element must have:\n"
    '- "key": a short snake_case identifier (e.g. "name", "favorite_language", "occupation")\n'
    '- "fact": a concise factual statement\n\n'
    "Rules:\n"
    "- Only extract facts the user has directly stated about themselves.\n"
    "- Do NOT invent, assume, or repeat facts.\n"
    "- If no new personal facts are present, output exactly: []\n\n"
    "Examples:\n"
    'User: "My name is Hassan" → [{"key": "name", "fact": "User\'s name is Hassan"}]\n'
    'User: "I prefer Python" → [{"key": "preferred_language", "fact": "User prefers Python programming language"}]\n'
    'User: "What is 2+2?" → []\n'
)


# ---------------------------------------------------------------------------
# Graph Nodes
# ---------------------------------------------------------------------------

async def chat_node(state: ChatState, config: RunnableConfig, *, store: BaseStore):
    """Main agent node — retrieves cross-thread memories and invokes the LLM."""
    messages = state["messages"]
    user_id = config.get("configurable", {}).get("user_id", "default")

    # Retrieve existing cross-thread memories for this user
    namespace = ("user_memories", user_id)
    memories = await store.asearch(namespace)

    memory_text = ""
    if memories:
        facts = [item.value.get("fact", "") for item in memories if item.value.get("fact")]
        if facts:
            memory_text = (
                "\n\nYou remember these facts about the user from previous conversations:\n"
                + "\n".join(f"- {f}" for f in facts)
                + "\n\nUse these facts naturally when relevant. Do not repeat them unless asked."
            )

    full_system_prompt = SYSTEM_PROMPT + memory_text

    # Always set the system prompt (replace existing or prepend)
    if messages and isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=full_system_prompt)] + list(messages[1:])
    else:
        messages = [SystemMessage(content=full_system_prompt)] + list(messages)

    response = await llm_with_tools.ainvoke(messages)
    return {"messages": [response]}


async def save_memories_node(state: ChatState, config: RunnableConfig, *, store: BaseStore):
    """Extract and persist user facts from the latest conversation exchange."""
    messages = state["messages"]
    user_id = config.get("configurable", {}).get("user_id", "default")
    namespace = ("user_memories", user_id)

    # Build conversation text from the last few messages
    recent = messages[-4:] if len(messages) > 4 else messages
    convo_lines = []
    for m in recent:
        if isinstance(m, HumanMessage):
            convo_lines.append(f"User: {m.content}")
        elif isinstance(m, AIMessage) and isinstance(m.content, str) and m.content:
            convo_lines.append(f"Assistant: {m.content}")

    convo_text = "\n".join(convo_lines)
    if not convo_text.strip():
        return {"messages": []}

    try:
        result = await memory_llm.ainvoke([
            SystemMessage(content=MEMORY_EXTRACTION_PROMPT),
            HumanMessage(content=f"Conversation:\n{convo_text}")
        ])
        content = result.content.strip()

        # Handle markdown code fences the LLM might wrap around JSON
        if "```" in content:
            parts = content.split("```")
            if len(parts) >= 2:
                content = parts[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

        facts = json.loads(content)

        if isinstance(facts, list):
            for fact in facts:
                if isinstance(fact, dict) and "key" in fact and "fact" in fact:
                    await store.aput(namespace, fact["key"], {"fact": fact["fact"]})
                    print(f"[Memory] Saved: {fact['key']} = {fact['fact']}")
    except Exception as e:
        # Never let memory extraction errors break the chat flow
        print(f"[Memory Extraction] Error: {e}")

    return {"messages": []}


# ---------------------------------------------------------------------------
# Graph Routing
# ---------------------------------------------------------------------------

def route_after_agent(state: ChatState):
    """Route to tools if the agent made tool calls, otherwise save memories."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "save_memories"


# ---------------------------------------------------------------------------
# Build Graph
# ---------------------------------------------------------------------------

graph = StateGraph(ChatState)

# Nodes
graph.add_node("agent", chat_node)
graph.add_node("tools", ToolNode(tools))
graph.add_node("save_memories", save_memories_node)

# Edges
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", route_after_agent)
graph.add_edge("tools", "agent")
graph.add_edge("save_memories", END)


# ---------------------------------------------------------------------------
# Async factory — PostgreSQL checkpointer + cross-thread store
# ---------------------------------------------------------------------------
_pool: AsyncConnectionPool | None = None
_store: AsyncPostgresStore | None = None
_compiled_graph = None


async def get_compiled_graph():
    """Lazily initialize the Postgres connection pool, set up the checkpoint
    tables and the cross-thread memory store, and compile the graph.
    """
    global _pool, _store, _compiled_graph

    if _compiled_graph is not None:
        return _compiled_graph

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Please set it in your .env file. Example: "
            "DATABASE_URL=postgresql://chatbot:chatbot_pass@localhost:5432/chatbot_db"
        )

    # Create an async connection pool for efficient Postgres access.
    # autocommit=True is required because setup() runs DDL like
    # CREATE INDEX CONCURRENTLY, which cannot execute inside a transaction.
    _pool = AsyncConnectionPool(
        conninfo=db_url,
        open=False,
        kwargs={"autocommit": True},
    )
    await _pool.open()

    # Checkpointer — per-thread conversation history
    checkpointer = AsyncPostgresSaver(_pool)
    await checkpointer.setup()

    # Store — cross-thread user memories
    _store = AsyncPostgresStore(conn=_pool)
    await _store.setup()

    _compiled_graph = graph.compile(checkpointer=checkpointer, store=_store)
    return _compiled_graph


async def close_pool():
    """Gracefully close the connection pool.  Call this during app shutdown."""
    global _pool, _store, _compiled_graph
    if _pool is not None:
        await _pool.close()
        _pool = None
    _store = None
    _compiled_graph = None

