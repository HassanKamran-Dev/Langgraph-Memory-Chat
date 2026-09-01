from langgraph.graph import StateGraph , START , END
from typing import TypedDict, Annotated
from langchain_core.messages import HumanMessage, BaseMessage
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
from langchain_groq import ChatGroq
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
import os
from dotenv import load_dotenv

load_dotenv()

class ChatState(TypedDict):

    messages: Annotated[list[BaseMessage], add_messages]

# I am commenting HuggingFace Code for using Groq API because i have hit the free limit
#hf_token = os.getenv("HUGGINGFACEHUB_API_TOKEN") or os.getenv("HF_TOKEN")

#llm = HuggingFaceEndpoint(
#    repo_id="meta-llama/Llama-3.1-8B-Instruct",
#    task="text-generation",
#    max_new_tokens=512,
#    do_sample=False,
#    huggingfacehub_api_token=hf_token,
#)

llm = ChatGroq(
    model="openai/gpt-oss-120b", # For instant non-reasoning responses use: "qwen/qwen3.8-27b"
    temperature=0.7,
    streaming=True
)

#model = ChatHuggingFace(llm=llm)

async def chat_node(state: ChatState):

    # take user query from state
    messages = state['messages']

    # send to llm asynchronously
    response = await llm.ainvoke(messages)

    # response store in state
    return {'messages': [response]}

checkpointer = MemorySaver()

# Made Graph
graph = StateGraph(ChatState)

# Add Nodes
graph.add_node("chat_node",chat_node)

# Add Edges
graph.add_edge(START,'chat_node')
graph.add_edge('chat_node',END)

chat_bot = graph.compile(checkpointer=checkpointer)
