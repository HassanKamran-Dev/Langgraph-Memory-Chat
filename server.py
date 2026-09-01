import os
import sys
import json
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
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


@app.post("/api/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    message_text = request.message.strip()
    thread_id = request.thread_id.strip() or "default-thread"

    if not message_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    async def event_generator():
        try:
            chat_bot = get_chat_bot()
            from langchain_core.messages import HumanMessage

            config = {"configurable": {"thread_id": thread_id}}
            input_data = {"messages": [HumanMessage(content=message_text)]}

            async for chunk, metadata in chat_bot.astream(
                input_data, config=config, stream_mode="messages"
            ):
                # Support reasoning/thinking tokens (e.g. gpt-oss-120b, DeepSeek-R1)
                if hasattr(chunk, "additional_kwargs") and chunk.additional_kwargs:
                    reasoning = (
                        chunk.additional_kwargs.get("reasoning_content")
                        or chunk.additional_kwargs.get("reasoning")
                    )
                    if reasoning:
                        data = json.dumps({"type": "reasoning", "content": reasoning})
                        yield f"data: {data}\n\n"

                # Direct token content
                if hasattr(chunk, "content") and chunk.content:
                    content = chunk.content
                    if isinstance(content, str) and content:
                        data = json.dumps({"type": "token", "content": content})
                        yield f"data: {data}\n\n"
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, str) and item:
                                data = json.dumps({"type": "token", "content": item})
                                yield f"data: {data}\n\n"
                            elif isinstance(item, dict) and "text" in item:
                                data = json.dumps({"type": "token", "content": item["text"]})
                                yield f"data: {data}\n\n"

            # Yield done event
            data = json.dumps({"type": "done", "thread_id": thread_id})
            yield f"data: {data}\n\n"

        except Exception as e:
            error_msg = str(e)
            print(f"Error during streaming: {error_msg}")
            data = json.dumps({"type": "error", "message": error_msg})
            yield f"data: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
