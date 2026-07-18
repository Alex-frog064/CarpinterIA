"""Hybrid vector store combining semantic (vector) search with BM25 keyword search
using Reciprocal Rank Fusion (RRF) to merge results."""

import json
import logging
import os
import pickle
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

SPANISH_STOPWORDS: set[str] = {
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "en", "con", "por", "para", "que", "es", "se", "no",
    "su", "al", "lo", "como", "más", "mas", "pero", "sus", "le", "ya",
    "o", "este", "sí", "porque", "esta", "entre", "cuando", "muy",
    "sin", "sobre", "también", "me", "hasta", "hay", "donde", "quien",
    "desde", "todo", "nos", "durante", "todos", "uno", "les", "ni",
    "contra", "otros", "ese", "eso", "ante", "ellos", "e", "esto",
    "mí", "antes", "algunos", "qué", "unos", "yo", "otro", "otras",
    "otra", "él", "tanto", "esa", "estos", "mucho", "quienes", "nada",
    "muchos", "cual", "sea", "poco", "ella", "estar", "estas", "algunas",
    "algo", "nosotros", "mi", "mis", "tú", "te", "ti", "tu", "tus",
    "ellas", "nosotras", "vosotros", "vosotras", "os", "mío", "mía",
    "míos", "mías", "tuyo", "tuya", "tuyos", "tuyas", "suyo", "suya",
    "suyos", "suyas", "nuestro", "nuestra", "nuestros", "nuestras",
    "vuestro", "vuestra", "vuestros", "vuestras", "esos", "esas",
    "estoy", "estás", "está", "estamos", "estáis", "están", "esté",
    "estés", "estemos", "estéis", "estén", "estaré", "estarás", "estará",
    "estaremos", "estaréis", "estarán", "estaría", "estarías", "estaríamos",
    "estaríais", "estarían", "estaba", "estabas", "estábamos", "estabais",
    "estaban", "estuve", "estuviste", "estuvo", "estuvimos", "estuvisteis",
    "estuvieron", "estuviera", "estuvieras", "estuviéramos", "estuvierais",
    "estuvieran", "estuviese", "estuvieses", "estuviésemos", "estuvieseis",
    "estuviesen", "estando", "estado", "estada", "estados", "estadas",
    "estad", "he", "has", "ha", "hemos", "habéis", "han", "haya",
    "hayas", "hayamos", "hayáis", "hayan", "habré", "habrás", "habrá",
    "habremos", "habréis", "habrán", "habría", "habrías", "habríamos",
    "habríais", "habrían", "había", "habías", "habíamos", "habíais",
    "habían", "hube", "hubiste", "hubo", "hubimos", "hubisteis", "hubieron",
    "hubiera", "hubieras", "hubiéramos", "hubierais", "hubieran", "hubiese",
    "hubieses", "hubiésemos", "hubieseis", "hubiesen", "habiendo",
    "habido", "habida", "habidos", "habidas", "soy", "eres", "es",
    "somos", "sois", "son", "sea", "seas", "seamos", "seáis", "sean",
    "seré", "serás", "será", "seremos", "seréis", "serán", "sería",
    "serías", "seríamos", "seríais", "serían", "era", "eras", "éramos",
    "erais", "eran", "fui", "fuiste", "fue", "fuimos", "fuisteis",
    "fueron", "fuera", "fueras", "fuéramos", "fuerais", "fueran", "fuese",
    "fueses", "fuésemos", "fueseis", "fuesen", "siendo", "tengo",
    "tienes", "tiene", "tenemos", "tenéis", "tienen", "tenga", "tengas",
    "tengamos", "tengáis", "tengan", "tendré", "tendrás", "tendrá",
    "tendremos", "tendréis", "tendrán", "tendría", "tendrías", "tendríamos",
    "tendríais", "tendrían", "tenía", "tenías", "teníamos", "teníais",
    "tenían", "tuve", "tuviste", "tuvo", "tuvimos", "tuvisteis", "tuvieron",
    "tuviera", "tuvieras", "tuviéramos", "tuvierais", "tuvieran", "tuviese",
    "tuvieses", "tuviésemos", "tuvieseis", "tuviesen", "teniendo", "tenido",
    "tenida", "tenidos", "tenidas", "tened",
}


class HybridVectorStore:
    """Hybrid vector store combining vector (semantic) search with BM25 keyword
    search using Reciprocal Rank Fusion (RRF) for result merging."""

    def __init__(self, persist_dir: str = "data/vector_store") -> None:
        self.persist_dir = Path(persist_dir)
        self.documents: list[dict] = []
        self.embeddings_matrix: np.ndarray | None = None
        self._bm25: BM25Okapi | None = None
        self._tokenized_corpus: list[list[str]] = []

    def add_documents(self, documents: list[dict]) -> None:
        """Add documents to the store.

        Each document must have: id, text, metadata, embedding.
        """
        for doc in documents:
            required = ("id", "text", "metadata", "embedding")
            missing = [k for k in required if k not in doc]
            if missing:
                raise ValueError(
                    f"Document missing required fields: {missing}. "
                    f"Provided keys: {list(doc.keys())}"
                )

        self.documents.extend(documents)
        self._rebuild_indices()
        logger.info("Added %d documents (total: %d)", len(documents), len(self.documents))

    def _rebuild_indices(self) -> None:
        """Rebuild the embeddings matrix and BM25 index from current documents."""
        if not self.documents:
            self.embeddings_matrix = None
            self._bm25 = None
            self._tokenized_corpus = []
            return

        embeddings = [np.array(doc["embedding"], dtype=np.float64) for doc in self.documents]
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        self.embeddings_matrix = embeddings / norms

        self._tokenized_corpus = [self._tokenize(doc["text"]) for doc in self.documents]
        self._bm25 = BM25Okapi(self._tokenized_corpus)
        logger.debug("Rebuilt indices for %d documents", len(self.documents))

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text: split on whitespace, lowercase, remove Spanish stopwords."""
        tokens = text.lower().split()
        return [t for t in tokens if t and t not in SPANISH_STOPWORDS]

    def vector_search(self, query_embedding: list[float], top_k: int = 10) -> list[dict]:
        """Pure vector (cosine similarity) search."""
        if not self.documents or self.embeddings_matrix is None:
            return []

        query_vec = np.array(query_embedding, dtype=np.float64)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []
        query_vec = query_vec / query_norm

        similarities = self.embeddings_matrix @ query_vec
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = []
        for idx in top_indices:
            results.append({
                "id": self.documents[idx]["id"],
                "text": self.documents[idx]["text"],
                "metadata": self.documents[idx]["metadata"],
                "score": float(similarities[idx]),
                "search_type": "vector",
            })
        return results

    def keyword_search(self, query: str, top_k: int = 10) -> list[dict]:
        """Pure BM25 keyword search."""
        if not self.documents or self._bm25 is None:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores = self._bm25.get_scores(query_tokens)
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            results.append({
                "id": self.documents[idx]["id"],
                "text": self.documents[idx]["text"],
                "metadata": self.documents[idx]["metadata"],
                "score": float(scores[idx]),
                "search_type": "keyword",
            })
        return results

    def hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int = 10,
        vector_weight: float = 0.6,
        bm25_weight: float = 0.4,
    ) -> list[dict]:
        """Combined hybrid search using Reciprocal Rank Fusion (RRF).

        RRF_score(d) = sum(1 / (k + rank_i(d)) for each ranking)
        where k = 60, rank_i is the rank in each ranking.
        """
        k = 60
        vector_results = self.vector_search(query_embedding, top_k=top_k)
        bm25_results = self.keyword_search(query, top_k=top_k)

        rrf_scores: dict[str, float] = {}
        doc_map: dict[str, dict] = {}

        for rank, result in enumerate(vector_results):
            doc_id = result["id"]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + vector_weight / (k + rank + 1)
            doc_map[doc_id] = result

        for rank, result in enumerate(bm25_results):
            doc_id = result["id"]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + bm25_weight / (k + rank + 1)
            if doc_id not in doc_map:
                doc_map[doc_id] = result

        sorted_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)[:top_k]

        results = []
        for doc_id in sorted_ids:
            entry = doc_map[doc_id]
            results.append({
                "id": entry["id"],
                "text": entry["text"],
                "metadata": entry["metadata"],
                "score": rrf_scores[doc_id],
                "search_type": "hybrid",
            })
        return results

    def search(self, query: str, query_embedding: list[float], top_k: int = 10) -> list[dict]:
        """Convenience method: performs hybrid search with default weights."""
        return self.hybrid_search(query, query_embedding, top_k=top_k)

    def get_document_count(self) -> int:
        """Return the number of documents in the store."""
        return len(self.documents)

    def clear(self) -> None:
        """Remove all documents and rebuild indices."""
        self.documents.clear()
        self._rebuild_indices()
        logger.info("Cleared all documents from vector store")

    def save(self) -> None:
        """Persist the store to disk.

        - documents.json: document data (without embeddings)
        - embeddings.pkl: numpy embeddings matrix
        """
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        docs_path = self.persist_dir / "documents.json"
        serializable = []
        for doc in self.documents:
            serializable.append({
                "id": doc["id"],
                "text": doc["text"],
                "metadata": doc["metadata"],
                "embedding": doc["embedding"],
            })
        with open(docs_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)

        embeddings_path = self.persist_dir / "embeddings.pkl"
        with open(embeddings_path, "wb") as f:
            pickle.dump(self.embeddings_matrix, f)

        logger.info("Saved %d documents to %s", len(self.documents), self.persist_dir)

    def load(self) -> None:
        """Load the store from disk."""
        docs_path = self.persist_dir / "documents.json"
        embeddings_path = self.persist_dir / "embeddings.pkl"

        if not docs_path.exists():
            raise FileNotFoundError(f"Documents file not found: {docs_path}")

        with open(docs_path, "r", encoding="utf-8") as f:
            self.documents = json.load(f)

        if embeddings_path.exists():
            with open(embeddings_path, "rb") as f:
                self.embeddings_matrix = pickle.load(f)
            # Verify shape matches
            if self.embeddings_matrix is not None and len(self.documents) > 0:
                if self.embeddings_matrix.shape[0] != len(self.documents):
                    logger.warning(
                        "Embedding matrix shape %s doesn't match document count %d, rebuilding",
                        self.embeddings_matrix.shape,
                        len(self.documents),
                    )
                    self.embeddings_matrix = None
        else:
            self.embeddings_matrix = None

        self._rebuild_indices()
        logger.info("Loaded %d documents from %s", len(self.documents), self.persist_dir)
