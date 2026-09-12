import os
import io
import json
import time
import re
import numpy as np
from typing import List, Dict, Any, Optional
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv

load_dotenv()

BASE_UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(BASE_UPLOADS_DIR, exist_ok=True)

# In-memory document store keyed by thread_id
# Structure:
# {
#    thread_id: {
#        "files": { filename: { "filename": str, "pages": int, "chunks": int, "uploaded_at": float } },
#        "chunks": [ { "text": str, "source": str, "page": int, "chunk_id": str } ],
#        "embeddings": np.ndarray or None,
#        "embedding_mode": "hf" | "local"
#    }
# }
_STORE: Dict[str, Dict[str, Any]] = {}

_hf_embeddings_instance = None


def get_hf_embeddings():
    global _hf_embeddings_instance
    if _hf_embeddings_instance is not None:
        return _hf_embeddings_instance

    token = os.getenv("HUGGINGFACEHUB_API_TOKEN") or os.getenv("HF_TOKEN")
    if not token:
        return None

    try:
        from langchain_huggingface import HuggingFaceEndpointEmbeddings
        _hf_embeddings_instance = HuggingFaceEndpointEmbeddings(
            model="sentence-transformers/all-MiniLM-L6-v2",
            huggingfacehub_api_token=token
        )
        return _hf_embeddings_instance
    except Exception as e:
        print(f"[RAG] Warning: Could not initialize HuggingFaceEndpointEmbeddings ({e}). Will use local vectorizer fallback.")
        return None


# --- Resilient Local Vectorizer (Fallback for offline / rate-limited situations) ---
class LocalTermVectorizer:
    """Lightweight TF-IDF / Subword frequency vectorizer using pure NumPy."""

    @staticmethod
    def tokenize(text: str) -> List[str]:
        words = re.findall(r"\b[a-zA-Z0-9_]{2,}\b", text.lower())
        # Add character 3-grams for robust typo & substring matching
        ngrams = []
        for w in words:
            if len(w) >= 3:
                ngrams.extend([w[i:i + 3] for i in range(len(w) - 2)])
        return words + ngrams

    @classmethod
    def embed_corpus(cls, texts: List[str]):
        # Build vocabulary
        token_doc_counts: Dict[str, int] = {}
        doc_tokens_list = []
        for text in texts:
            tokens = cls.tokenize(text)
            unique_tokens = set(tokens)
            for t in unique_tokens:
                token_doc_counts[t] = token_doc_counts.get(t, 0) + 1
            doc_tokens_list.append(tokens)

        # Select top features
        sorted_vocab = sorted(token_doc_counts.items(), key=lambda x: x[1], reverse=True)[:2048]
        vocab = {item[0]: idx for idx, item in enumerate(sorted_vocab)}
        vocab_size = len(vocab)
        n_docs = max(1, len(texts))

        if vocab_size == 0:
            return np.zeros((len(texts), 1), dtype=np.float32), vocab, np.zeros((1,), dtype=np.float32)

        # Compute IDF
        idf = np.zeros(vocab_size, dtype=np.float32)
        for term, idx in vocab.items():
            df = token_doc_counts.get(term, 1)
            idf[idx] = np.log((1 + n_docs) / (1 + df)) + 1.0

        # Compute TF-IDF matrix
        matrix = np.zeros((len(texts), vocab_size), dtype=np.float32)
        for doc_idx, tokens in enumerate(doc_tokens_list):
            for t in tokens:
                if t in vocab:
                    matrix[doc_idx, vocab[t]] += 1.0
            # Length normalize
            norm = np.linalg.norm(matrix[doc_idx])
            if norm > 0:
                matrix[doc_idx] = (matrix[doc_idx] * idf) / norm

        return matrix, vocab, idf

    @classmethod
    def embed_query(cls, query: str, vocab: Dict[str, int], idf: np.ndarray) -> np.ndarray:
        vocab_size = len(vocab)
        if vocab_size == 0:
            return np.zeros((1,), dtype=np.float32)
        vec = np.zeros(vocab_size, dtype=np.float32)
        tokens = cls.tokenize(query)
        for t in tokens:
            if t in vocab:
                vec[vocab[t]] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = (vec * idf) / norm
        return vec


def _get_thread_dir(thread_id: str) -> str:
    # Sanitize thread_id for file system
    clean_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", thread_id)
    thread_dir = os.path.join(BASE_UPLOADS_DIR, clean_id)
    os.makedirs(thread_dir, exist_ok=True)
    return thread_dir


def _ensure_thread_store(thread_id: str) -> Dict[str, Any]:
    if thread_id in _STORE:
        return _STORE[thread_id]

    thread_dir = _get_thread_dir(thread_id)
    index_file = os.path.join(thread_dir, "index.json")
    embeddings_file = os.path.join(thread_dir, "embeddings.npy")

    if os.path.exists(index_file):
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            embeddings = None
            if os.path.exists(embeddings_file):
                embeddings = np.load(embeddings_file)
            _STORE[thread_id] = {
                "files": data.get("files", {}),
                "chunks": data.get("chunks", []),
                "embeddings": embeddings,
                "embedding_mode": data.get("embedding_mode", "hf"),
                "vocab": data.get("vocab", {}),
                "idf": np.array(data.get("idf", []), dtype=np.float32) if data.get("idf") else None
            }
            return _STORE[thread_id]
        except Exception as e:
            print(f"[RAG] Failed to reload store from disk for thread {thread_id}: {e}")

    _STORE[thread_id] = {
        "files": {},
        "chunks": [],
        "embeddings": None,
        "embedding_mode": "hf",
        "vocab": {},
        "idf": None
    }
    return _STORE[thread_id]


def _persist_thread_store(thread_id: str):
    store = _STORE.get(thread_id)
    if not store:
        return

    thread_dir = _get_thread_dir(thread_id)
    index_file = os.path.join(thread_dir, "index.json")
    embeddings_file = os.path.join(thread_dir, "embeddings.npy")

    try:
        meta = {
            "files": store["files"],
            "chunks": store["chunks"],
            "embedding_mode": store.get("embedding_mode", "hf"),
            "vocab": store.get("vocab", {}),
            "idf": store.get("idf").tolist() if store.get("idf") is not None else []
        }
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        if store.get("embeddings") is not None:
            np.save(embeddings_file, store["embeddings"])
    except Exception as e:
        print(f"[RAG] Failed persisting index for thread {thread_id}: {e}")


def process_pdf(file_bytes: bytes, filename: str, thread_id: str = "default-thread") -> Dict[str, Any]:
    """
    Extracts text from a PDF, splits into chunks with page metadata,
    computes embeddings, and updates the thread's vector index.
    """
    store = _ensure_thread_store(thread_id)
    thread_dir = _get_thread_dir(thread_id)

    # Save original PDF file
    saved_pdf_path = os.path.join(thread_dir, filename)
    with open(saved_pdf_path, "wb") as f:
        f.write(file_bytes)

    # Extract text per page
    reader = PdfReader(io.BytesIO(file_bytes))
    total_pages = len(reader.pages)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=150,
        separators=["\n\n", "\n", ". ", " ", ""]
    )

    new_chunks = []
    for page_idx, page in enumerate(reader.pages):
        page_num = page_idx + 1
        page_text = page.extract_text() or ""
        page_text = page_text.strip()
        if not page_text:
            continue

        splits = splitter.split_text(page_text)
        for split_idx, split_content in enumerate(splits):
            chunk_content = split_content.strip()
            if len(chunk_content) < 10:
                continue
            new_chunks.append({
                "text": chunk_content,
                "source": filename,
                "page": page_num,
                "chunk_id": f"{filename}_p{page_num}_c{split_idx}"
            })

    if not new_chunks:
        # Document had no extractable text
        store["files"][filename] = {
            "filename": filename,
            "pages": total_pages,
            "chunks": 0,
            "uploaded_at": time.time(),
            "empty": True
        }
        _persist_thread_store(thread_id)
        return {
            "filename": filename,
            "pages": total_pages,
            "chunks": 0,
            "message": "PDF processed, but no extractable text was found (it may contain scanned images)."
        }

    # Remove any existing chunks for this file if re-uploaded
    store["chunks"] = [c for c in store["chunks"] if c["source"] != filename] + new_chunks
    store["files"][filename] = {
        "filename": filename,
        "pages": total_pages,
        "chunks": len(new_chunks),
        "uploaded_at": time.time()
    }

    # Compute Embeddings for all chunks in this thread
    all_texts = [c["text"] for c in store["chunks"]]
    hf = get_hf_embeddings()
    embedded_successfully = False

    if hf is not None:
        try:
            print(f"[RAG] Embedding {len(all_texts)} chunks with HuggingFace endpoint for thread {thread_id}...")
            embeddings_list = hf.embed_documents(all_texts)
            store["embeddings"] = np.array(embeddings_list, dtype=np.float32)
            store["embedding_mode"] = "hf"
            embedded_successfully = True
        except Exception as e:
            print(f"[RAG] HuggingFace embedding call failed ({e}). Switching to local term vectorizer.")

    if not embedded_successfully:
        print(f"[RAG] Computing local semantic embeddings for {len(all_texts)} chunks...")
        matrix, vocab, idf = LocalTermVectorizer.embed_corpus(all_texts)
        store["embeddings"] = matrix
        store["vocab"] = vocab
        store["idf"] = idf
        store["embedding_mode"] = "local"

    _persist_thread_store(thread_id)

    return {
        "filename": filename,
        "pages": total_pages,
        "chunks": len(new_chunks),
        "total_thread_chunks": len(store["chunks"]),
        "embedding_mode": store["embedding_mode"]
    }


def search_documents(query: str, thread_id: str = "default-thread", top_k: int = 4) -> List[Dict[str, Any]]:
    """
    Performs cosine similarity search over the thread's indexed document chunks.
    Falls back to global documents if none found for thread_id.
    """
    store = _ensure_thread_store(thread_id)
    chunks = store.get("chunks", [])

    # If no chunks in this thread, check default-thread or any other active thread
    if not chunks and thread_id != "default-thread":
        fallback_store = _ensure_thread_store("default-thread")
        if fallback_store.get("chunks"):
            store = fallback_store
            chunks = store.get("chunks", [])

    if not chunks or store.get("embeddings") is None:
        return []

    query_str = query.strip()
    if not query_str:
        return []

    embeddings = store["embeddings"]
    mode = store.get("embedding_mode", "hf")
    query_vec = None

    if mode == "hf":
        hf = get_hf_embeddings()
        if hf is not None:
            try:
                raw_vec = hf.embed_query(query_str)
                query_vec = np.array(raw_vec, dtype=np.float32)
            except Exception as e:
                print(f"[RAG] HuggingFace query embedding failed ({e}). Fallback to local search.")

    if query_vec is None:
        # Use local query embedding
        vocab = store.get("vocab")
        idf = store.get("idf")
        if vocab is not None and idf is not None and len(vocab) > 0:
            query_vec = LocalTermVectorizer.embed_query(query_str, vocab, idf)
        else:
            # Rebuild local vectorizer on the fly
            all_texts = [c["text"] for c in chunks]
            matrix, vocab, idf = LocalTermVectorizer.embed_corpus(all_texts)
            embeddings = matrix
            store["embeddings"] = matrix
            store["vocab"] = vocab
            store["idf"] = idf
            store["embedding_mode"] = "local"
            query_vec = LocalTermVectorizer.embed_query(query_str, vocab, idf)

    if query_vec is None or len(query_vec) == 0:
        return []

    # Calculate Cosine Similarities
    # norm(query_vec)
    query_norm = np.linalg.norm(query_vec)
    if query_norm < 1e-9:
        return []

    # norms for each doc chunk
    doc_norms = np.linalg.norm(embeddings, axis=1)
    # avoid division by zero
    doc_norms[doc_norms < 1e-9] = 1e-9

    dot_products = np.dot(embeddings, query_vec)
    similarities = dot_products / (doc_norms * query_norm)

    top_indices = np.argsort(similarities)[::-1][:top_k]

    results = []
    for idx in top_indices:
        score = float(similarities[idx])
        chunk = chunks[idx]
        results.append({
            "text": chunk["text"],
            "source": chunk["source"],
            "page": chunk["page"],
            "score": score
        })

    return results


def get_documents(thread_id: str = "default-thread") -> List[Dict[str, Any]]:
    """Returns the list of uploaded documents and their metadata for a given thread."""
    store = _ensure_thread_store(thread_id)
    files_dict = store.get("files", {})
    return list(files_dict.values())


def delete_document(filename: str, thread_id: str = "default-thread") -> bool:
    """Deletes a document and its embeddings from the thread store and disk."""
    store = _ensure_thread_store(thread_id)
    if filename not in store.get("files", {}):
        return False

    del store["files"][filename]
    store["chunks"] = [c for c in store["chunks"] if c["source"] != filename]

    all_texts = [c["text"] for c in store["chunks"]]
    if all_texts:
        # Re-compute embeddings
        hf = get_hf_embeddings()
        if hf is not None and store.get("embedding_mode") == "hf":
            try:
                embeddings_list = hf.embed_documents(all_texts)
                store["embeddings"] = np.array(embeddings_list, dtype=np.float32)
            except Exception:
                matrix, vocab, idf = LocalTermVectorizer.embed_corpus(all_texts)
                store["embeddings"] = matrix
                store["vocab"] = vocab
                store["idf"] = idf
                store["embedding_mode"] = "local"
        else:
            matrix, vocab, idf = LocalTermVectorizer.embed_corpus(all_texts)
            store["embeddings"] = matrix
            store["vocab"] = vocab
            store["idf"] = idf
            store["embedding_mode"] = "local"
    else:
        store["embeddings"] = None
        store["vocab"] = {}
        store["idf"] = None

    thread_dir = _get_thread_dir(thread_id)
    file_on_disk = os.path.join(thread_dir, filename)
    if os.path.exists(file_on_disk):
        try:
            os.remove(file_on_disk)
        except Exception:
            pass

    _persist_thread_store(thread_id)
    return True
