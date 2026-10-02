import time
import unittest
from unittest.mock import patch

from ai_engine import AIEngine
from faq_vector_engine import FAQVectorEngine
from knowledge_service import KnowledgeAnswerService


class FakeEmbeddingAI:
    def rewrite_question(self, question):
        return {"rewritten_question": question}

    def create_embedding(self, text):
        return [1.0, 0.0] if "سند" in str(text) else [0.0, 1.0]

    def create_embeddings(self, texts):
        return [self.create_embedding(text) for text in texts]


class FakeComposerAI:
    def __init__(self, source_ids=None, confidence=0.91):
        self.source_ids = source_ids or ["faq:1", "doc:2"]
        self.confidence = confidence

    def decompose_question(self, question):
        return ["ثبت سند چگونه است؟", "موجودی انبار چگونه کنترل می‌شود؟"]

    def compose_grounded_answer(self, question, subquestions, evidence):
        return {
            "answer": "ثبت سند و کنترل موجودی طبق منابع تأییدشده انجام می‌شود.",
            "used_source_ids": self.source_ids,
            "answered_parts": subquestions,
            "unanswered_parts": [],
            "confidence": self.confidence,
        }


class FakeRetriever:
    def find_evidence(self, subquestions):
        return [
            {
                "source_id": "faq:1",
                "title": "ثبت سند",
                "content": "مراحل ثبت سند",
                "category": "حسابداری",
                "source_type": "faq",
                "version": "",
                "score": 0.92,
            },
            {
                "source_id": "doc:2",
                "title": "کنترل موجودی",
                "content": "راهنمای کنترل موجودی",
                "category": "انبار",
                "source_type": "guide",
                "version": "2",
                "score": 0.89,
            },
        ]


class AIEngineTests(unittest.TestCase):
    def test_json_parser_accepts_fenced_json(self):
        fence = chr(96) * 3
        result = AIEngine._parse_json_object(
            fence + 'json\n{"type":"product_question","confidence":0.9}\n' + fence
        )
        self.assertEqual(result["type"], "product_question")
        self.assertEqual(result["confidence"], 0.9)

    def test_offline_router_keeps_clarification_separate_from_support(self):
        result = AIEngine._route_message_offline(
            "این قسمت رو نفهمیدم",
            "پاسخ قبلی وجود دارد",
        )
        self.assertEqual(result["type"], "clarification_request")

    def test_grounded_answer_uses_strong_evidence_when_api_fails(self):
        engine = AIEngine()
        evidence = [
            {
                "source_id": "faq:1",
                "title": "ثبت سند",
                "content": "مراحل تأییدشده ثبت سند",
                "score": 0.94,
            }
        ]
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch.object(engine, "_complete", side_effect=RuntimeError("offline")):
                result = engine.compose_grounded_answer(
                    "ثبت سند چگونه است؟",
                    ["ثبت سند چگونه است؟"],
                    evidence,
                )
        self.assertEqual(result["used_source_ids"], ["faq:1"])
        self.assertIn("مراحل تأییدشده", result["answer"])


class RetrieverTests(unittest.TestCase):
    def setUp(self):
        self.retriever = FAQVectorEngine(engine=None, ai=FakeEmbeddingAI())
        self.retriever.minimum_score = 0.2
        self.retriever._cached_sources = [
            {
                "source_id": "faq:1",
                "record_id": 1,
                "source_type": "faq",
                "title": "ثبت سند حسابداری",
                "content": "مراحل ثبت سند",
                "category": "حسابداری",
                "keywords": "سند",
                "source_reference": "",
                "version": "",
                "updated_at": "",
                "_embedding": [1.0, 0.0],
            },
            {
                "source_id": "doc:2",
                "record_id": 2,
                "source_type": "guide",
                "title": "کنترل موجودی انبار",
                "content": "راهنمای موجودی",
                "category": "انبار",
                "keywords": "",
                "source_reference": "",
                "version": "2",
                "updated_at": "",
                "_embedding": [0.0, 1.0],
            },
        ]
        self.retriever._cached_at = time.monotonic()

    def test_retrieves_different_sources_for_composite_question(self):
        evidence = self.retriever.find_evidence(
            ["ثبت سند چگونه است؟", "موجودی انبار چگونه کنترل می‌شود؟"],
            per_query=2,
        )
        self.assertEqual(
            {item["source_id"] for item in evidence},
            {"faq:1", "doc:2"},
        )

    def test_evidence_is_deduplicated_by_source_id(self):
        evidence = self.retriever.find_evidence(
            ["ثبت سند", "ثبت سند حسابداری"],
            per_query=2,
        )
        ids = [item["source_id"] for item in evidence]
        self.assertEqual(len(ids), len(set(ids)))


class KnowledgeAnswerServiceTests(unittest.TestCase):
    def test_combines_multiple_approved_sources(self):
        service = KnowledgeAnswerService(
            FakeRetriever(),
            FakeComposerAI(),
            minimum_confidence=0.7,
        )
        result = service.answer("ثبت سند و کنترل موجودی را توضیح بده")
        self.assertIsNotNone(result)
        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual(result["category"], "حسابداری، انبار")

    def test_rejects_answer_that_claims_unknown_source(self):
        service = KnowledgeAnswerService(
            FakeRetriever(),
            FakeComposerAI(source_ids=["faq:1", "doc:999"]),
            minimum_confidence=0.7,
        )
        self.assertIsNone(service.answer("یک سؤال ترکیبی"))

    def test_rejects_low_confidence_answer(self):
        service = KnowledgeAnswerService(
            FakeRetriever(),
            FakeComposerAI(confidence=0.4),
            minimum_confidence=0.7,
        )
        self.assertIsNone(service.answer("یک سؤال ترکیبی"))


if __name__ == "__main__":
    unittest.main()
