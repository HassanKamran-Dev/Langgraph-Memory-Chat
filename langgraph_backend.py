from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
from langchain_core.messages import HumanMessage, BaseMessage, SystemMessage
from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
import os
from dotenv import load_dotenv
import rag_service

load_dotenv()


class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# RAG Retrieval Tool
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

llm = ChatGroq(
    model="openai/gpt-oss-120b",  # Supports function calling & reasoning
    temperature=0.7,
    streaming=True
)

llm_with_tools = llm.bind_tools(tools)

SYSTEM_PROMPT = (
    "You are a helpful, knowledgeable, and concise conversational AI assistant. "
    "You have access to tools `search_uploaded_documents` and `list_uploaded_documents` to query files uploaded by the user. "
    "Whenever the user asks questions about their uploaded documents, PDFs, or files, always invoke `search_uploaded_documents` "
    "to retrieve accurate information. "
    "When answering based on retrieved documents, always cite the document name and page number (e.g. '[Document: filename.pdf, Page X]'). "
    "If no relevant documents are found or uploaded, let the user know they can upload PDF files using the attachment icon."
)


async def chat_node(state: ChatState):
    messages = state["messages"]

    # Prepend system prompt if not present
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)

    response = await llm_with_tools.ainvoke(messages)
    return {"messages": [response]}


checkpointer = MemorySaver()

# Build Graph
graph = StateGraph(ChatState)

# Add Nodes
graph.add_node("agent", chat_node)
graph.add_node("tools", ToolNode(tools))

# Add Edges
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", tools_condition)
graph.add_edge("tools", "agent")

chat_bot = graph.compile(checkpointer=checkpointer)

