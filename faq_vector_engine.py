from sqlalchemy import text
from rapidfuzz import fuzz

from ai_engine import ai_engine


class FAQVectorEngine:

    def __init__(self, engine):
        self.engine = engine

    def load_faqs(self):
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT id, question, answer, category
                    FROM dbo.knowledge_base
                    WHERE question IS NOT NULL
                      AND answer IS NOT NULL
                """)
            ).mappings().all()

        return [dict(row) for row in rows]

    def normalize_question(self, text):
        if not text:
            return ""

        return str(text).strip()

    def find_best_match(self, user_question):
        original_question = str(user_question or "").strip()

        if not original_question:
            return {
                "best": None,
                "top_matches": [],
                "rewrite": None,
                "judge": None,
                "judge_confidence": 0.0
            }

        rewrite_result = ai_engine.rewrite_question(
            original_question
        )

        rewritten_question = rewrite_result.get(
            "rewritten_question",
            original_question
        )

        search_question = self.normalize_question(
            rewritten_question
        )

        if not search_question:
            search_question = original_question

        faqs = self.load_faqs()

        results = []

        for item in faqs:
            faq_question = str(
                item.get("question") or ""
            ).strip()

            if not faq_question:
                continue

            semantic_score = ai_engine.similarity(
                search_question,
                faq_question
            )

            fuzzy_score = fuzz.token_set_ratio(
                search_question,
                faq_question
            ) / 100.0

            final_score = (
                semantic_score * 0.90
                +
                fuzzy_score * 0.10
            )

            results.append({
                "item": item,
                "score": float(final_score),
                "semantic_score": float(semantic_score),
                "fuzzy_score": float(fuzzy_score)
            })

        results.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        top_matches = results[:5]

        if not top_matches:
            return {
                "best": None,
                "top_matches": [],
                "rewrite": rewrite_result,
                "judge": None,
                "judge_confidence": 0.0
            }

        candidates = [
            match["item"]
            for match in top_matches
        ]

        judge_result = ai_engine.select_best_faq(
            original_question=original_question,
            candidates=candidates
        )

        selected_id = judge_result.get("selected_id")

        judge_confidence = judge_result.get(
            "confidence",
            0.0
        )

        try:
            judge_confidence = float(judge_confidence)
        except (TypeError, ValueError):
            judge_confidence = 0.0

        selected_match = None

        if selected_id is not None:
            for match in top_matches:
                if str(match["item"]["id"]) == str(selected_id):
                    selected_match = match
                    break

        if judge_confidence < 0.80:
            selected_match = None

        return {
            "best": selected_match,
            "top_matches": top_matches,
            "rewrite": rewrite_result,
            "judge": judge_result,
            "judge_confidence": judge_confidence
        }
