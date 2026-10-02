import os
from typing import Any, Dict, Optional


class KnowledgeAnswerService:
    """Orchestrates decomposition, retrieval and grounded answer composition."""

    def __init__(self, retriever, ai, minimum_confidence: Optional[float] = None):
        self.retriever = retriever
        self.ai = ai
        self.minimum_confidence = (
            float(minimum_confidence)
            if minimum_confidence is not None
            else float(os.getenv("KNOWLEDGE_ANSWER_MIN_CONFIDENCE", "0.68"))
        )

    def answer(self, question: str) -> Optional[Dict[str, Any]]:
        clean_question = str(question or "").strip()
        if not clean_question:
            return None

        subquestions = self.ai.decompose_question(clean_question)
        if not subquestions:
            subquestions = [clean_question]

        evidence = self.retriever.find_evidence(subquestions)
        if not evidence:
            return None

        composition = self.ai.compose_grounded_answer(
            clean_question,
            subquestions,
            evidence,
        )
        answer = str(composition.get("answer") or "").strip()
        confidence = self._safe_float(composition.get("confidence"))
        available_ids = {
            str(item.get("source_id"))
            for item in evidence
            if item.get("source_id")
        }
        used_ids = [
            str(source_id)
            for source_id in composition.get("used_source_ids") or []
            if str(source_id) in available_ids
        ]

        # Reject answers with invented source IDs or without strong enough
        # evidence. The caller can then send the user to human support.
        claimed_ids = {
            str(source_id)
            for source_id in composition.get("used_source_ids") or []
        }
        if (
            not answer
            or not used_ids
            or claimed_ids != set(used_ids)
            or confidence < self.minimum_confidence
        ):
            return None

        used_evidence = [
            item for item in evidence if str(item.get("source_id")) in set(used_ids)
        ]
        sources = [
            {
                "id": item["source_id"],
                "title": item.get("title") or "منبع دانش",
                "category": item.get("category") or "عمومی",
                "type": item.get("source_type") or "manual",
                "version": item.get("version") or "",
            }
            for item in used_evidence
        ]
        categories = []
        for item in used_evidence:
            category = str(item.get("category") or "عمومی").strip()
            if category and category not in categories:
                categories.append(category)

        return {
            "answer": answer,
            "subquestions": subquestions,
            "answered_parts": self._strings(composition.get("answered_parts")),
            "unanswered_parts": self._strings(composition.get("unanswered_parts")),
            "sources": sources,
            "matched_questions": [
                str(item.get("title") or "").strip()
                for item in used_evidence
                if str(item.get("title") or "").strip()
            ],
            "category": "، ".join(categories) or "پایگاه دانش",
            "confidence": confidence,
        }

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _strings(values: Any):
        if not isinstance(values, list):
            return []
        return [str(item).strip() for item in values if str(item or "").strip()]
