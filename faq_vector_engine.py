import os
import time
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz
from sqlalchemy import text

from ai_engine import ai_engine


class FAQVectorEngine:
    """Hybrid search over approved FAQ and long-form knowledge documents."""

    def __init__(self, engine, ai=None):
        self.engine = engine
        self.ai = ai or ai_engine
        self.cache_ttl_seconds = int(os.getenv("KNOWLEDGE_CACHE_TTL_SECONDS", "300"))
        self.minimum_score = float(os.getenv("KNOWLEDGE_RETRIEVAL_MIN_SCORE", "0.43"))
        self._cached_sources: List[Dict[str, Any]] = []
        self._cached_at = 0.0

    def invalidate_cache(self) -> None:
        self._cached_sources = []
        self._cached_at = 0.0

    def load_faqs(self) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, question, answer, category, keywords_text, updated_at
                    FROM dbo.knowledge_base
                    WHERE is_active = 1
                      AND question IS NOT NULL
                      AND answer IS NOT NULL
                    """
                )
            ).mappings().all()
        return [dict(row) for row in rows]

    def _load_documents(self) -> List[Dict[str, Any]]:
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT
                            id,
                            title,
                            content,
                            category,
                            source_type,
                            source_reference,
                            version,
                            updated_at
                        FROM dbo.knowledge_documents
                        WHERE is_active = 1
                          AND approval_status = N'approved'
                          AND title IS NOT NULL
                          AND content IS NOT NULL
                        """
                    )
                ).mappings().all()
        except Exception:
            # Allows the application to start once before init_db creates the
            # new table and keeps older databases compatible during migration.
            return []
        return [dict(row) for row in rows]

    def load_sources(self, force: bool = False) -> List[Dict[str, Any]]:
        now = time.monotonic()
        cache_is_fresh = (
            self._cached_sources
            and now - self._cached_at < self.cache_ttl_seconds
        )
        if cache_is_fresh and not force:
            return self._cached_sources

        sources: List[Dict[str, Any]] = []
        for row in self.load_faqs():
            sources.append(
                {
                    "source_id": f'faq:{row["id"]}',
                    "record_id": int(row["id"]),
                    "source_type": "faq",
                    "title": str(row.get("question") or "").strip(),
                    "content": str(row.get("answer") or "").strip(),
                    "category": str(row.get("category") or "عمومی").strip(),
                    "keywords": str(row.get("keywords_text") or "").strip(),
                    "source_reference": "",
                    "version": "",
                    "updated_at": row.get("updated_at"),
                }
            )
        for row in self._load_documents():
            sources.append(
                {
                    "source_id": f'doc:{row["id"]}',
                    "record_id": int(row["id"]),
                    "source_type": str(row.get("source_type") or "manual").strip(),
                    "title": str(row.get("title") or "").strip(),
                    "content": str(row.get("content") or "").strip(),
                    "category": str(row.get("category") or "عمومی").strip(),
                    "keywords": "",
                    "source_reference": str(row.get("source_reference") or "").strip(),
                    "version": str(row.get("version") or "").strip(),
                    "updated_at": row.get("updated_at"),
                }
            )

        searchable_texts = [
            self._source_search_text(item)
            for item in sources
        ]
        try:
            embeddings = self.ai.create_embeddings(searchable_texts)
        except Exception:
            embeddings = [None] * len(sources)

        for index, source in enumerate(sources):
            source["_embedding"] = embeddings[index] if index < len(embeddings) else None

        self._cached_sources = sources
        self._cached_at = now
        return self._cached_sources

    @staticmethod
    def normalize_question(value: str) -> str:
        return " ".join(str(value or "").strip().split())

    @staticmethod
    def _source_search_text(source: Dict[str, Any]) -> str:
        return " | ".join(
            part
            for part in [
                str(source.get("title") or "").strip(),
                str(source.get("keywords") or "").strip(),
                str(source.get("category") or "").strip(),
                str(source.get("content") or "").strip()[:1800],
            ]
            if part
        )

    @staticmethod
    def _dot_similarity(first: Any, second: Any) -> float:
        if first is None or second is None:
            return 0.0
        try:
            return float(sum(float(a) * float(b) for a, b in zip(first, second)))
        except Exception:
            return 0.0

    def find_matches(self, user_question: str, limit: int = 5) -> List[Dict[str, Any]]:
        original_question = self.normalize_question(user_question)
        if not original_question:
            return []

        rewrite = self.ai.rewrite_question(original_question)
        search_question = self.normalize_question(
            rewrite.get("rewritten_question") or original_question
        )
        sources = self.load_sources()
        if not sources:
            return []

        try:
            query_embedding = self.ai.create_embedding(search_question)
        except Exception:
            query_embedding = None

        results: List[Dict[str, Any]] = []
        for source in sources:
            searchable_title = " ".join(
                [
                    str(source.get("title") or ""),
                    str(source.get("keywords") or ""),
                    str(source.get("category") or ""),
                ]
            )
            fuzzy_score = fuzz.token_set_ratio(search_question, searchable_title) / 100.0
            semantic_score = self._dot_similarity(
                query_embedding,
                source.get("_embedding"),
            )
            if query_embedding is None or source.get("_embedding") is None:
                final_score = fuzzy_score
            else:
                final_score = semantic_score * 0.82 + fuzzy_score * 0.18

            if final_score < self.minimum_score:
                continue
            public_source = {
                key: value
                for key, value in source.items()
                if key != "_embedding"
            }
            public_source.update(
                {
                    "score": float(final_score),
                    "semantic_score": float(semantic_score),
                    "fuzzy_score": float(fuzzy_score),
                    "matched_query": original_question,
                }
            )
            results.append(public_source)

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[: max(1, int(limit))]

    def find_evidence(
        self,
        subquestions: List[str],
        per_query: int = 4,
        max_total: int = 10,
    ) -> List[Dict[str, Any]]:
        best_by_id: Dict[str, Dict[str, Any]] = {}
        for question in subquestions:
            for match in self.find_matches(question, limit=per_query):
                source_id = str(match.get("source_id"))
                previous = best_by_id.get(source_id)
                if previous is None or match["score"] > previous["score"]:
                    best_by_id[source_id] = match

        results = sorted(
            best_by_id.values(),
            key=lambda item: item["score"],
            reverse=True,
        )
        return results[:max_total]

    def find_best_match(self, user_question: str) -> Dict[str, Any]:
        """Compatibility adapter for older callers."""
        matches = self.find_matches(user_question, limit=5)
        top_matches = [
            {
                "item": {
                    "id": item["record_id"],
                    "question": item["title"],
                    "answer": item["content"],
                    "category": item["category"],
                },
                "score": item["score"],
                "semantic_score": item["semantic_score"],
                "fuzzy_score": item["fuzzy_score"],
            }
            for item in matches
        ]
        best = top_matches[0] if top_matches else None
        return {
            "best": best,
            "top_matches": top_matches,
            "rewrite": None,
            "judge": None,
            "judge_confidence": best["score"] if best else 0.0,
        }
