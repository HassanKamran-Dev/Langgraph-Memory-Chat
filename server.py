import os
import sys
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="Pure Conversation - LangGraph Chatbot")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default-thread"


_cached_backend = None


def get_chat_bot():
    global _cached_backend
    if _cached_backend is None:
        import langgraph_backend
        _cached_backend = langgraph_backend

    for name in ["chat_bot", "chatbot", "graph", "app", "bot"]:
        if hasattr(_cached_backend, name):
            return getattr(_cached_backend, name)

    raise ValueError(
        "No compiled graph found in `langgraph_backend.py`. "
        "Please ensure your compiled graph is assigned to `chat_bot = graph.compile(...)`."
    )


@app.get("/")
async def get_index():
    return FileResponse("static/index.html")


@app.get("/api/status")
async def get_status():
    try:
        chat_bot = get_chat_bot()
        return {"status": "ok", "backend_ready": chat_bot is not None}
    except Exception as e:
        return {"status": "error", "detail": str(e), "backend_ready": False}


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    message_text = request.message.strip()
    thread_id = request.thread_id.strip() or "default-thread"

    if not message_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        chat_bot = get_chat_bot()

        # Prepare LangGraph input format
        from langchain_core.messages import HumanMessage

        config = {"configurable": {"thread_id": thread_id}}
        input_data = {"messages": [HumanMessage(content=message_text)]}

        # Invoke LangGraph with thread configuration
        result = chat_bot.invoke(input_data, config=config)

        # Extract latest AI message from result
        response_text = ""
        if isinstance(result, dict) and "messages" in result:
            messages = result["messages"]
            if messages:
                last_msg = messages[-1]
                if hasattr(last_msg, "content"):
                    response_text = last_msg.content
                elif isinstance(last_msg, dict) and "content" in last_msg:
                    response_text = last_msg["content"]
                else:
                    response_text = str(last_msg)
        elif hasattr(result, "content"):
            response_text = result.content
        else:
            response_text = str(result)

        return {"response": response_text, "thread_id": thread_id}

    except Exception as e:
        print(f"Error executing chat_bot: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"LangGraph execution error: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
