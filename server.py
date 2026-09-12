import os
import sys
import json
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import rag_service

# Load environment variables
load_dotenv()

app = FastAPI(title="Pure Conversation - LangGraph Chatbot")

# Prevent browser from serving stale cached assets during development
@app.middleware("http")
async def add_cache_control_headers(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

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
    return FileResponse(
        "static/index.html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


@app.get("/api/status")
async def get_status():
    try:
        chat_bot = get_chat_bot()
        return {"status": "ok", "backend_ready": chat_bot is not None}
    except Exception as e:
        return {"status": "error", "detail": str(e), "backend_ready": False}


@app.post("/api/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    thread_id: str = Form("default-thread")
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        res = rag_service.process_pdf(file_bytes, file.filename, thread_id=thread_id)
        return {
            "status": "success",
            "filename": file.filename,
            "pages": res.get("pages", 1),
            "chunks": res.get("chunks", 0),
            "total_thread_chunks": res.get("total_thread_chunks", 0),
            "thread_id": thread_id,
            "embedding_mode": res.get("embedding_mode", "hf")
        }
    except Exception as e:
        print(f"[Upload Error]: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")


@app.get("/api/documents")
async def get_documents(thread_id: str = Query("default-thread")):
    try:
        docs = rag_service.get_documents(thread_id=thread_id)
        return {"documents": docs, "thread_id": thread_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/documents/{filename}")
async def delete_document(filename: str, thread_id: str = Query("default-thread")):
    try:
        success = rag_service.delete_document(filename, thread_id=thread_id)
        return {"success": success, "filename": filename, "thread_id": thread_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
                node = metadata.get("langgraph_node")

                # If from tools execution node, notify frontend with a status event
                if node == "tools":
                    data = json.dumps({"type": "status", "content": "Analyzing document excerpts..."})
                    yield f"data: {data}\n\n"
                    continue

                # If LLM emits tool call request
                if hasattr(chunk, "tool_calls") and chunk.tool_calls:
                    data = json.dumps({"type": "status", "content": "Searching uploaded document..."})
                    yield f"data: {data}\n\n"
                    continue

                if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
                    continue

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
