"""Main RAG pipeline orchestrator.

Combines document loading, chunking, embedding, vector storage, hybrid search,
and reranking into a single cohesive pipeline.
"""

import hashlib
import logging
import os
import re
import time
from pathlib import Path

import numpy as np

from .embeddings import EmbeddingService
from .vector_store import HybridVectorStore

logger = logging.getLogger(__name__)


class RerankerService:
    """Lightweight reranker using query-keyword overlap scoring.

    When a cross-encoder model is available via Ollama it could be used here;
    for now, this provides a deterministic scoring heuristic that still
    improves ranking over raw hybrid search.
    """

    def __init__(self):
        self._stopwords: set[str] = {
            "el", "la", "los", "las", "un", "una", "de", "del", "en", "con",
            "por", "para", "que", "es", "se", "no", "su", "al", "lo", "como",
            "mas", "pero", "sus", "le", "ya", "o", "este", "sí", "porque",
            "esta", "entre", "cuando", "muy", "sin", "sobre", "tambien", "me",
            "hasta", "hay", "donde", "quien", "desde", "todo", "nos", "durante",
            "todos", "uno", "les", "ni", "contra", "otros", "ese", "eso",
            "ante", "ellos", "esto", "antes", "algunos", "yo", "otro", "otra",
        }

    def _tokenize(self, text: str) -> list[str]:
        tokens = re.findall(r"\w+", text.lower())
        return [t for t in tokens if t not in self._stopwords and len(t) > 1]

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = 3,
    ) -> list[dict]:
        """Rerank candidates by keyword overlap and original hybrid score.

        Combines BM25-like keyword overlap ratio with the incoming hybrid score.
        """
        query_tokens = set(self._tokenize(query))
        if not query_tokens:
            return candidates[:top_k]

        scored: list[tuple[float, dict]] = []
        max_hybrid = max((c.get("score", 0) for c in candidates), default=1.0)
        if max_hybrid == 0:
            max_hybrid = 1.0

        for doc in candidates:
            doc_tokens = set(self._tokenize(doc.get("text", "")))
            if not doc_tokens:
                overlap = 0.0
            else:
                overlap = len(query_tokens & doc_tokens) / len(query_tokens)

            hybrid_norm = doc.get("score", 0) / max_hybrid
            combined = 0.4 * hybrid_norm + 0.6 * overlap
            scored.append((combined, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]


class RAGPipeline:
    """Orchestrates the full RAG flow: load → chunk → embed → index → query."""

    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        embedding_model: str = "nomic-embed-text",
        persist_dir: str = "data/vector_store",
        documents_dir: str = "documents",
    ):
        self.documents_dir = Path(documents_dir)
        self.persist_dir = Path(persist_dir)

        self.embedding_service = EmbeddingService(
            ollama_base_url=ollama_base_url,
            embedding_model=embedding_model,
        )
        self.vector_store = HybridVectorStore(persist_dir=str(self.persist_dir))
        self.reranker = RerankerService()

        self._initialized = False
        self._all_chunks: list[dict] = []

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Load persisted index or build from scratch."""
        docs_path = self.persist_dir / "documents.json"
        if docs_path.exists():
            logger.info("Loading existing vector store from %s", self.persist_dir)
            self.vector_store.load()
            self._all_chunks = list(self.vector_store.documents)
            self._initialized = True
            logger.info("Loaded %d chunks from disk", len(self._all_chunks))
            return

        logger.info("No persisted index found — building from documents in %s", self.documents_dir)
        raw_docs = self.load_documents_from_dir(str(self.documents_dir))
        if not raw_docs:
            logger.warning("No documents found in %s", self.documents_dir)
            self._initialized = True
            return

        await self.index_documents(raw_docs)
        self._initialized = True

    # ------------------------------------------------------------------
    # Document loading
    # ------------------------------------------------------------------

    def load_documents_from_dir(self, doc_dir: str) -> list[dict]:
        """Read every .txt file in *doc_dir* and return raw document dicts."""
        directory = Path(doc_dir)
        if not directory.exists():
            logger.warning("Documents directory does not exist: %s", directory)
            return []

        documents: list[dict] = []
        for txt_file in sorted(directory.glob("*.txt")):
            try:
                text = txt_file.read_text(encoding="utf-8")
                documents.append({
                    "filename": txt_file.name,
                    "text": text,
                })
                logger.debug("Loaded %s (%d chars)", txt_file.name, len(text))
            except Exception as exc:
                logger.error("Failed to read %s: %s", txt_file, exc)

        logger.info("Loaded %d document files from %s", len(documents), directory)
        return documents

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------

    def chunk_document(
        self,
        text: str,
        source: str,
        chunk_size: int = 500,
        overlap: int = 100,
    ) -> list[dict]:
        """Split *text* into overlapping chunks with metadata.

        Strategy:
        1. Split on ``## `` section headers to preserve logical structure.
        2. Within each section, split on paragraph boundaries (``\\n\\n``).
        3. Merge paragraphs until *chunk_size* (in words) is reached.
        4. If a single paragraph exceeds *chunk_size*, split on sentence
           boundaries, then on word boundaries as a last resort.
        5. Apply *overlap* words from the end of the previous chunk to the
           start of the next.
        """
        sections = self._split_sections(text)
        chunks: list[dict] = []
        chunk_idx = 0
        tail_words: list[str] = []

        for section_title, section_text in sections:
            paragraphs = re.split(r"\n\n+", section_text)
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue

                para_words = para.split()
                if len(para_words) <= chunk_size:
                    combined_words = tail_words + para_words
                    chunk_text = " ".join(combined_words)
                    chunks.append(self._make_chunk(chunk_text, source, chunk_idx, section_title))
                    chunk_idx += 1
                    tail_words = combined_words[-overlap:] if overlap else []
                else:
                    sub_chunks = self._split_large_block(para, chunk_size, overlap)
                    for sc in sub_chunks:
                        combined_words = tail_words + sc.split()
                        chunk_text = " ".join(combined_words)
                        chunks.append(self._make_chunk(chunk_text, source, chunk_idx, section_title))
                        chunk_idx += 1
                        tail_words = combined_words[-overlap:] if overlap else []

        return chunks

    @staticmethod
    def _split_sections(text: str) -> list[tuple[str, str]]:
        """Split text on ``## `` headers, returning (title, body) pairs."""
        parts = re.split(r"(?=^## )", text, flags=re.MULTILINE)
        sections: list[tuple[str, str]] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            header_match = re.match(r"^## (.+)$", part, re.MULTILINE)
            if header_match:
                title = header_match.group(1).strip()
                body = part[header_match.end():]
            else:
                title = ""
                body = part
            sections.append((title, body))
        return sections

    @staticmethod
    def _split_large_block(text: str, chunk_size: int, overlap: int) -> list[str]:
        """Split a block that exceeds *chunk_size* words."""
        sentences = re.split(r"(?<=\. )", text)
        result: list[str] = []
        current_words: list[str] = []

        for sentence in sentences:
            sent_words = sentence.split()
            if len(current_words) + len(sent_words) <= chunk_size:
                current_words.extend(sent_words)
            else:
                if current_words:
                    result.append(" ".join(current_words))
                # If a single sentence is still too large, force-split on words
                if len(sent_words) > chunk_size:
                    for i in range(0, len(sent_words), chunk_size - overlap):
                        chunk = sent_words[i : i + chunk_size]
                        result.append(" ".join(chunk))
                    current_words = sent_words[-overlap:] if overlap else []
                else:
                    current_words = sent_words

        if current_words:
            result.append(" ".join(current_words))

        return result

    @staticmethod
    def _make_chunk(
        text: str,
        source: str,
        index: int,
        section_title: str = "",
    ) -> dict:
        chunk_id = hashlib.sha256(f"{source}::{index}".encode()).hexdigest()[:16]
        return {
            "id": chunk_id,
            "text": text,
            "metadata": {
                "source": source,
                "chunk_index": index,
                "section": section_title,
            },
        }

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    async def index_documents(self, documents: list[dict]) -> None:
        """Chunk, embed, and add documents to the vector store."""
        all_chunks: list[dict] = []
        for doc in documents:
            chunks = self.chunk_document(doc["text"], doc["filename"])
            all_chunks.extend(chunks)

        if not all_chunks:
            logger.warning("No chunks produced from %d documents", len(documents))
            return

        logger.info("Embedding %d chunks ...", len(all_chunks))
        texts = [c["text"] for c in all_chunks]
        embeddings = await self.embedding_service.embed_texts(texts)

        indexed: list[dict] = []
        for chunk, embedding in zip(all_chunks, embeddings):
            indexed.append({
                "id": chunk["id"],
                "text": chunk["text"],
                "metadata": chunk["metadata"],
                "embedding": embedding,
            })

        self.vector_store.add_documents(indexed)
        self._all_chunks = list(self.vector_store.documents)

        self.vector_store.save()
        logger.info("Indexed and persisted %d chunks", len(indexed))

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def query(self, question: str, top_k: int = 3) -> dict:
        """Full RAG query pipeline with timing.

        Returns:
            dict with keys: context, sources, chunks, timing
        """
        timing: dict[str, float] = {}
        t0 = time.perf_counter()

        # Step 1: embed query
        t = time.perf_counter()
        query_embedding = await self.embedding_service.embed_text(question)
        timing["embed"] = round(time.perf_counter() - t, 4)

        # Step 2: hybrid search (always retrieve more candidates)
        t = time.perf_counter()
        search_top_k = max(top_k * 3, 10)
        candidates = self.vector_store.search(question, query_embedding, top_k=search_top_k)
        timing["search"] = round(time.perf_counter() - t, 4)

        # Step 3: rerank
        t = time.perf_counter()
        reranked = self.reranker.rerank(question, candidates, top_k=top_k)
        timing["rerank"] = round(time.perf_counter() - t, 4)

        timing["total"] = round(time.perf_counter() - t0, 4)

        # Step 4: format context
        context_parts: list[str] = []
        sources: list[str] = []
        for chunk in reranked:
            source = chunk.get("metadata", {}).get("source", "desconocido")
            context_parts.append(f"Fuente: {source}\n{chunk['text']}\n---")
            if source not in sources:
                sources.append(source)

        context = "\n\n".join(context_parts)

        return {
            "context": context,
            "sources": sources,
            "chunks": reranked,
            "timing": timing,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_context_for_query(self, question: str, top_k: int = 3) -> str:
        """Synchronous convenience: return the formatted context string."""
        loop = __import__("asyncio").get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    __import__("asyncio").run,
                    self.query(question, top_k=top_k),
                )
                result = future.result()
        else:
            result = loop.run_until_complete(self.query(question, top_k=top_k))
        return result["context"]

    def get_stats(self) -> dict:
        """Return index statistics."""
        doc_count = self.vector_store.get_document_count()
        sources: set[str] = set()
        for doc in self.vector_store.documents:
            src = doc.get("metadata", {}).get("source", "")
            if src:
                sources.add(src)
        return {
            "document_count": len(sources),
            "chunk_count": doc_count,
            "sources": sorted(sources),
            "persist_dir": str(self.persist_dir),
            "initialized": self._initialized,
        }
