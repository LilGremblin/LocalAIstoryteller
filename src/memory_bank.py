"""
Memory Bank — Semantic long-term memory using FAISS + sentence-transformers.
Stores compressed memories and retrieves relevant ones via embedding similarity.
"""

import os
import json
import numpy as np
from src import config

# Lazy-loaded globals to avoid slow import at startup
_model = None
_faiss = None


def _load_faiss():
    global _faiss
    if _faiss is None:
        import faiss
        _faiss = faiss
    return _faiss


def _load_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        model_name = config.get("EMBEDDING_MODEL", config.EMBEDDING_MODEL)
        _model = SentenceTransformer(model_name)
    return _model


class MemoryBank:
    """
    Semantic memory storage and retrieval.
    Each memory is a text chunk + embedding vector stored in a FAISS index.
    """

    def __init__(self, dimension: int = 384):
        self.dimension = dimension
        self.memories: list[dict] = []  # {"text": str, "turn": int, "type": str}
        self.index = None
        self._initialized = False

    def _ensure_index(self):
        """Lazily create the FAISS index."""
        if not self._initialized:
            faiss = _load_faiss()
            self.index = faiss.IndexFlatIP(self.dimension)  # Inner product for cosine sim
            self._initialized = True

    def add_memory(self, text: str, turn: int, memory_type: str = "summary"):
        """
        Add a new memory to the bank.
        
        Args:
            text: The memory text to store.
            turn: The story turn number this memory relates to.
            memory_type: "summary", "event", "character", etc.
        """
        if not text.strip():
            return

        self._ensure_index()
        model = _load_model()

        # Generate embedding
        embedding = model.encode([text], normalize_embeddings=True).astype("float32")

        # Store
        self.index.add(embedding)
        self.memories.append({
            "text": text,
            "turn": turn,
            "type": memory_type,
        })

    def search(self, query: str, top_k: int | None = None) -> list[dict]:
        """
        Search for memories relevant to the query.
        
        Returns list of {"text": str, "turn": int, "type": str, "score": float}
        sorted by relevance (highest first).
        """
        if not self._initialized or self.index is None or self.index.ntotal == 0:
            return []

        top_k = top_k or config.get("MEMORY_TOP_K", config.MEMORY_TOP_K)
        min_score = config.get("MEMORY_MIN_SCORE", config.MEMORY_MIN_SCORE)
        top_k = min(top_k, self.index.ntotal)

        model = _load_model()
        query_embedding = model.encode([query], normalize_embeddings=True).astype("float32")

        scores, indices = self.index.search(query_embedding, top_k)

        results = []
        for i, idx in enumerate(indices[0]):
            if idx < 0 or idx >= len(self.memories):
                continue
            score = float(scores[0][i])
            if score < min_score:
                continue
            memory = dict(self.memories[idx])
            memory["score"] = score
            results.append(memory)

        return results

    def build_memory_text(self, query: str, max_tokens: int) -> str:
        """
        Retrieve relevant memories and format them as a context block.
        """
        from src.token_manager import count_tokens, truncate_to_tokens

        results = self.search(query)
        if not results:
            return ""

        lines = ["[Recalled Memories]"]
        total_tokens = count_tokens("[Recalled Memories]\n")

        for mem in results:
            line = f"- (Turn {mem['turn']}): {mem['text']}"
            line_tokens = count_tokens(line + "\n")
            if total_tokens + line_tokens > max_tokens:
                remaining = max_tokens - total_tokens - 10
                if remaining > 20:
                    truncated = truncate_to_tokens(mem["text"], remaining)
                    lines.append(f"- (Turn {mem['turn']}): {truncated}")
                break
            lines.append(line)
            total_tokens += line_tokens

        if len(lines) <= 1:
            return ""

        return "\n".join(lines)

    def save(self, directory: str, name: str):
        """Save the memory bank to disk."""
        os.makedirs(directory, exist_ok=True)

        # Save memories list
        mem_path = os.path.join(directory, f"{name}_memories.json")
        with open(mem_path, "w", encoding="utf-8") as f:
            json.dump(self.memories, f, indent=2, ensure_ascii=False)

        # Save FAISS index
        if self._initialized and self.index is not None and self.index.ntotal > 0:
            faiss = _load_faiss()
            idx_path = os.path.join(directory, f"{name}_index.faiss")
            faiss.write_index(self.index, idx_path)

    def load(self, directory: str, name: str) -> bool:
        """Load a memory bank from disk. Returns True if successful."""
        mem_path = os.path.join(directory, f"{name}_memories.json")
        idx_path = os.path.join(directory, f"{name}_index.faiss")

        if not os.path.exists(mem_path):
            return False

        with open(mem_path, "r", encoding="utf-8") as f:
            self.memories = json.load(f)

        if os.path.exists(idx_path):
            faiss = _load_faiss()
            self.index = faiss.read_index(idx_path)
            self._initialized = True
        else:
            # Rebuild index from memories
            if self.memories:
                self._ensure_index()
                model = _load_model()
                texts = [m["text"] for m in self.memories]
                embeddings = model.encode(
                    texts, normalize_embeddings=True
                ).astype("float32")
                self.index.add(embeddings)

        return True

    def clear(self):
        """Clear all memories."""
        self.memories = []
        self.index = None
        self._initialized = False

    @property
    def count(self) -> int:
        return len(self.memories)
