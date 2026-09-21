# Pure Conversation - LangGraph Chatbot 🤖✨

---

## 🌟 Features

- **🧠 Long-Term Memory (PostgreSQL)**: Conversations persist across server restarts via `AsyncPostgresSaver`, and user facts (name, preferences, interests) are remembered across different chat sessions via `AsyncPostgresStore` — powered by a Dockerized PostgreSQL instance.
- **🔗 Cross-Thread Memory**: The bot automatically extracts and stores personal facts you share (e.g. your name, favorite language) and recalls them in every new chat, not just within the same conversation thread.
- **📄 PDF RAG Tool (Retrieval-Augmented Generation)**: Upload any PDF directly via the attachment button (📎) or drag-and-drop. The backend chunks, embeds, and indexes the document using vector similarity with `HuggingFaceEndpointEmbeddings` (and resilient local fallback).
- **🛠️ LangGraph Tool Calling Agent**: The AI autonomously determines when to invoke the `search_uploaded_documents` tool to fetch relevant excerpts and synthesize answers with precise document and page-level citations (`[Document: file.pdf, Page X]`).
- **🗂️ Collapsible Sidebar Navigation**: Sleek, responsive sidebar with a desktop toggle and mobile slide-over drawer with backdrop overlay.
- **➕ One-Click New Chat**: Instantly initialize fresh conversation threads with the "+ New Chat" button or the `Ctrl+N` (`Cmd+N`) shortcut.
- **💬 Recent Chats History**: Automatically saves conversations with titles derived from your initial prompt, displays active thread indicators, and allows one-click switching and individual chat deletion.
- **💾 Local Persistence & Memory Continuity**: Chat histories are preserved in browser `localStorage`, with each session maintaining its unique LangGraph `thread_id` so context is retained when jumping between chats.
- **⚡ Real-Time SSE Token Streaming**: Streams tokens from LangGraph directly to the frontend using Server-Sent Events (SSE) via `/api/chat/stream`.
- **✨ Silky Smooth Typing Animation**: Frontend token queue with `requestAnimationFrame` ensures fluid, typewriter-like rendering without browser stutter or jumping.
- **💭 Live Thought Process UI**: Displays expandable live reasoning/thinking accordions for reasoning models (e.g. `openai/gpt-oss-120b`, DeepSeek-R1) before collapsing seamlessly into the final answer.
- **⏹️ Stop Generation**: Built-in `AbortController` allows users to pause or cancel response generation mid-stream.
- **📜 Smart Auto-Scroll**: High-performance scrolling keeps up with incoming tokens while automatically pausing if you scroll up to read earlier messages.
- **🎨 Premium Stitch Aesthetics**: Clean typography, warm color palette, code syntax styling, and glowing streaming cursors.

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl + N` / `Cmd + N` | Start a **New Chat** |
| `Enter` | **Send** message |
| `Shift + Enter` | Insert a **new line** in the message input |
| `Esc` | Close mobile sidebar |

---

## 🏗️ Architecture

```mermaid
sequenceDiagram
    autonumber
    actor User as Web Browser (app.js)
    participant Server as FastAPI Server (/api/chat/stream)
    participant Graph as LangGraph StateGraph
    participant CP as AsyncPostgresSaver (Checkpointer)
    participant Store as AsyncPostgresStore (Cross-Thread Memory)
    participant LLM as Groq / Hugging Face LLM
    participant PG as PostgreSQL (Docker)

    User->>Server: POST /api/chat/stream { message, thread_id }
    Server->>Graph: astream(input, config={thread_id, user_id}, stream_mode="messages")
    Graph->>CP: Load conversation history for thread_id
    Graph->>Store: Retrieve user memories (namespace: user_memories/user_id)
    Graph->>LLM: ainvoke(system_prompt + memories + messages)
    loop Stream Chunks
        LLM-->>Graph: AIMessageChunk (reasoning / content)
        Graph-->>Server: yield (chunk, metadata)
        Server-->>User: SSE event: data: {"type": "reasoning" | "token", "content": "..."}
        User->>User: Smooth buffer render & auto-scroll
    end
    Graph->>LLM: Extract user facts from conversation
    Graph->>Store: Save new user facts (e.g. name, preferences)
    Graph->>CP: Persist new state checkpoint to PostgreSQL
    Server-->>User: SSE event: data: {"type": "done", "thread_id": "..."}
```

---

## 📁 Project Structure

```text
Langgraph-Memory-Chat/
├── .env.example            # Environment variables template (API keys & DATABASE_URL)
├── .gitignore              # Git ignore rules for virtualenv & secrets
├── README.md               # Project documentation
├── requirements.txt        # Python package dependencies
├── docker-compose.yml      # PostgreSQL 16 container for long-term memory
├── langgraph_backend.py    # LangGraph StateGraph, AsyncPostgresSaver, AsyncPostgresStore & LLM config
├── rag_service.py          # PDF processing, embedding & vector search for RAG
├── server.py               # FastAPI server, lifespan handler & streaming SSE endpoints
├── test_rag.py             # RAG service tests
└── static/
    ├── index.html          # Stitch "Pure Conversation" layout with responsive sidebar
    ├── style.css           # Sidebar transitions, micro-animations & custom scrollbars
    └── app.js              # Multi-session state, streaming SSE consumer & UI logic
```

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python 3.10+**
- **Docker** (for PostgreSQL — [Install Docker Desktop](https://www.docker.com/products/docker-desktop/))
- An API Key:
  - **Groq API Key (Recommended)**: Get a free key from [console.groq.com/keys](https://console.groq.com/keys).
  - *or* **Hugging Face Token**: Get one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).

### 2. Clone the Repository
```bash
git clone https://github.com/HassanKamran-Dev/Langgraph-Memory-Chat.git
cd Langgraph-Memory-Chat
```

### 3. Create & Activate Virtual Environment
- **Windows (PowerShell)**:
  ```powershell
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  ```
- **macOS / Linux**:
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables
Create a `.env` file in the root directory (or copy from `.env.example`):
```bash
cp .env.example .env
```

Add your API key and database URL inside `.env`:
```env
# Groq (Recommended)
GROQ_API_KEY=gsk_your_groq_api_key_here

# Hugging Face (Optional alternative)
HUGGINGFACEHUB_API_TOKEN=hf_your_token_here

# PostgreSQL (Required for long-term memory)
DATABASE_URL=postgresql://chatbot:chatbot_pass@localhost:5432/chatbot_db
```

### 6. Start PostgreSQL (Docker)
```bash
docker compose up -d
```
This spins up a PostgreSQL 16 container. The database tables (checkpoints, store) are created automatically on first startup.

### 7. Run the Application
```bash
python server.py
```

You should see:
```
[startup] PostgreSQL checkpointer initialised — long-term memory active
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Open your browser and navigate to:
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

---

## 🧠 Long-Term Memory

The chatbot has two layers of persistent memory, both backed by PostgreSQL:

| Layer | Technology | Scope | What It Stores |
|-------|-----------|-------|----------------|
| **Per-Thread** | `AsyncPostgresSaver` | Within a single chat | Full conversation history (survives server restarts) |
| **Cross-Thread** | `AsyncPostgresStore` | Across all chats | User facts: name, preferences, interests, etc. |

### How It Works
1. When you chat, the **agent node** retrieves your stored facts from the cross-thread store and includes them in the system prompt
2. After the agent responds, the **save_memories node** uses the LLM to extract any new personal facts you shared
3. Facts are stored with semantic keys (e.g. `name`, `preferred_language`) — restating a fact updates it instead of duplicating

### Example
- **Chat 1**: *"My name is Hassan and I prefer Python"* → Bot saves `name` and `preferred_language`
- **Chat 2**: *"What's my name?"* → Bot recalls *"Hassan"* from the store

### Inspect Stored Memories
```bash
docker exec -it chatbot-postgres psql -U chatbot -d chatbot_db -c "SELECT * FROM store;"
```

---

## 🛠️ Model Configuration

You can customize the model and settings inside [`langgraph_backend.py`](langgraph_backend.py):

### 1. Instant Streaming (Fast Chat)
For immediate word-by-word streaming with zero delay:
```python
llm = ChatGroq(
    model="qwen/qwen3.8-27b",  # or "qwen/qwen3.6-27b"
    temperature=0.7,
    streaming=True
)
```

### 2. Reasoning Models (Deep Thought Process)
To stream the model's internal thinking process in a collapsible "Thinking..." block before receiving the answer:
```python
llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0.7,
    streaming=True
)
```

### 3. Hugging Face Inference
To use Hugging Face instead, uncomment the `HuggingFaceEndpoint` configuration:
```python
llm = HuggingFaceEndpoint(
    repo_id="meta-llama/Llama-3.1-8B-Instruct",
    task="text-generation",
    max_new_tokens=512,
    huggingfacehub_api_token=os.getenv("HUGGINGFACEHUB_API_TOKEN"),
)
```

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/chat/stream` | Real-time Server-Sent Events (SSE) streaming endpoint |
| `POST` | `/api/chat` | Synchronous / non-streaming JSON response endpoint |
| `POST` | `/api/upload` | Upload a PDF for RAG document indexing |
| `GET` | `/api/documents` | List uploaded documents for a thread |
| `DELETE` | `/api/documents/{filename}` | Delete an uploaded document |
| `GET` | `/api/status` | Health check verifying LangGraph backend compilation status |
| `GET` | `/` | Serves the Pure Conversation web application |
