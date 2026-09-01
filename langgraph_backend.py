from langgraph.graph import StateGraph , START , END
from typing import TypedDict, Annotated
from langchain_core.messages import HumanMessage, BaseMessage
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
import os
from dotenv import load_dotenv

load_dotenv()

class ChatState(TypedDict):

    messages: Annotated[list[BaseMessage], add_messages]

hf_token = os.getenv("HUGGINGFACEHUB_API_TOKEN") or os.getenv("HF_TOKEN")

llm = HuggingFaceEndpoint(
    repo_id="meta-llama/Llama-3.1-8B-Instruct",
    task="text-generation",
    max_new_tokens=512,
    do_sample=False,
    huggingfacehub_api_token=hf_token,
)

model = ChatHuggingFace(llm=llm)

def chat_node(state: ChatState):

    # take user query from state
    messages = state['messages']

    # send to llm
    response = model.invoke(messages)

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
