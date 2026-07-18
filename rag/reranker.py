"""Cross-encoder reranker for a RAG pipeline.

Re-scores retrieved document chunks against the user query to improve relevance.
Falls back to a heuristic scorer when sentence-transformers is not available.
"""

import logging
import re
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)


class RerankerService:
    """Re-ranks retrieved documents using a cross-encoder or heuristic fallback."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model_name = model_name
        self._model: Optional["CrossEncoder"] = None
        self._use_cross_encoder = False

        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(model_name)
            self._use_cross_encoder = True
            logger.info(
                "Reranker using cross-encoder model: %s",
                model_name,
            )
        except ImportError:
            logger.info(
                "sentence-transformers not available, using fallback heuristic scorer",
            )
        except Exception as exc:
            logger.warning(
                "Failed to load cross-encoder model '%s': %s; using fallback scorer",
                model_name,
                exc,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rerank(
        self,
        query: str,
        documents: list[dict],
        top_k: int = 3,
    ) -> list[dict]:
        """Rerank documents by relevance to the query, returning the top_k.

        Each document in the input list should contain:
            id, text, score, metadata

        A ``rerank_score`` field is added to each returned document.
        """
        if not query or not documents:
            return []

        for doc in documents:
            doc["rerank_score"] = self.score(query, doc.get("text", ""))

        documents.sort(key=lambda d: d["rerank_score"], reverse=True)
        return documents[:top_k]

    def score(self, query: str, document: str) -> float:
        """Score a single query-document pair, returning a float in [0, 1]."""
        if not query or not document:
            return 0.0

        if self._use_cross_encoder and self._model is not None:
            return self._cross_encoder_score(query, document)

        return self._fallback_score(query, document)

    def bulk_rerank(
        self,
        query: str,
        documents: list[dict],
        top_k: int = 3,
    ) -> list[dict]:
        """Batch rerank: same as ``rerank`` but may use batched inference.

        When the cross-encoder is available, all query-document pairs are
        scored in a single forward pass for efficiency.
        """
        if not query or not documents:
            return []

        if self._use_cross_encoder and self._model is not None:
            texts = [doc.get("text", "") for doc in documents]
            pairs = [(query, t) for t in texts]
            try:
                scores = self._model.predict(pairs)
                for doc, score in zip(documents, scores):
                    doc["rerank_score"] = self._normalize(float(score))
            except Exception as exc:
                logger.error("Cross-encoder bulk prediction failed: %s", exc)
                for doc in documents:
                    doc["rerank_score"] = self.score(query, doc.get("text", ""))
        else:
            for doc in documents:
                doc["rerank_score"] = self.score(query, doc.get("text", ""))

        documents.sort(key=lambda d: d["rerank_score"], reverse=True)
        return documents[:top_k]

    # ------------------------------------------------------------------
    # Cross-encoder scoring
    # ------------------------------------------------------------------

    def _cross_encoder_score(self, query: str, document: str) -> float:
        """Score via sentence-transformers CrossEncoder."""
        try:
            if self._model is None:
                return self._fallback_score(query, document)
            score = self._model.predict([(query, document)])[0]
            return self._normalize(float(score))
        except Exception as exc:
            logger.debug("Cross-encoder scoring failed: %s", exc)
            return self._fallback_score(query, document)

    @staticmethod
    def _normalize(score: float) -> float:
        """Sigmoid-like normalisation to [0, 1].

        Cross-encoder logits can be any real value; a sigmoid maps them to
        a probability-like range.
        """
        return 1.0 / (1.0 + (2.71828 ** (-score)))

    # ------------------------------------------------------------------
    # Fallback heuristic scorer
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Lowercase tokenisation on word boundaries, ignoring non-alpha tokens."""
        tokens = re.findall(r"[a-záéíóúüñ]+", text.lower())
        return [t for t in tokens if len(t) > 1]

    def _fallback_score(self, query: str, document: str) -> float:
        """Heuristic relevance score based on token overlap.

        Combines:
          - Jaccard similarity of query and document tokens
          - Term-frequency count of query terms in the document
          - Length penalty for very short or very long documents
          - Title match bonus from metadata (not available here, so unused)
        """
        query_tokens = self._tokenize(query)
        doc_tokens = self._tokenize(document)

        if not query_tokens or not doc_tokens:
            return 0.0

        query_set = set(query_tokens)
        doc_set = set(doc_tokens)

        # --- Jaccard similarity ---
        intersection = query_set & doc_set
        union = query_set | doc_set
        jaccard = len(intersection) / len(union) if union else 0.0

        # --- Term frequency ---
        doc_counter = Counter(doc_tokens)
        tf_sum = sum(doc_counter[t] for t in intersection)
        max_tf = max(doc_counter.values()) if doc_counter else 1
        tf_ratio = tf_sum / (len(query_tokens) * max_tf) if max_tf > 0 else 0.0

        # --- Length penalty ---
        doc_len = len(doc_tokens)
        # Optimal length range: 30-200 tokens
        if doc_len < 10:
            len_penalty = 0.3
        elif doc_len < 30:
            len_penalty = 0.5 + (doc_len / 30) * 0.5
        elif doc_len <= 200:
            len_penalty = 1.0
        else:
            len_penalty = max(0.0, 1.0 - (doc_len - 200) / 800)

        # --- Combined score ---
        score = 0.5 * jaccard + 0.3 * tf_ratio + 0.2 * len_penalty
        return min(max(score, 0.0), 1.0)
