import unittest

import app as app_module


class AskFlowTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        app_module.app.config.update(TESTING=True)
        with self.client.session_transaction() as flask_session:
            flask_session["logged_in"] = True
            flask_session["user_id"] = 1
            flask_session["role"] = "admin"

        self.original_route_message = app_module.ai_engine.route_message
        self.original_clarify = app_module.ai_engine.clarify_previous_answer
        self.original_answer = app_module.knowledge_answer_service.answer

    def tearDown(self):
        app_module.ai_engine.route_message = self.original_route_message
        app_module.ai_engine.clarify_previous_answer = self.original_clarify
        app_module.knowledge_answer_service.answer = self.original_answer

    def test_two_step_clarification_preserves_original_answer(self):
        app_module.ai_engine.clarify_previous_answer = (
            lambda message, previous_question, previous_answer:
            "کدام قسمت پاسخ را متوجه نشدید؟"
        )
        first = self.client.post(
            "/ask",
            json={
                "question": "نفهمیدم",
                "previous_question": "چطور سند ثبت کنم؟",
                "previous_answer": "از منوی حسابداری وارد ثبت سند شوید.",
            },
        )
        first_data = first.get_json()
        self.assertTrue(first_data["preserve_context"])
        self.assertTrue(first_data["awaiting_clarification_detail"])

        app_module.ai_engine.clarify_previous_answer = (
            lambda message, previous_question, previous_answer:
            "برای ثبت سند، ابتدا وارد منوی حسابداری شوید."
        )
        second = self.client.post(
            "/ask",
            json={
                "question": "قسمت ثبت سند",
                "previous_question": "چطور سند ثبت کنم؟",
                "previous_answer": "از منوی حسابداری وارد ثبت سند شوید.",
                "awaiting_clarification_detail": True,
            },
        )
        second_data = second.get_json()
        self.assertTrue(second_data["preserve_context"])
        self.assertFalse(second_data["awaiting_clarification_detail"])
        self.assertIn("ثبت سند", second_data["answers"][0])

    def test_grounded_answer_returns_sources(self):
        app_module.ai_engine.route_message = (
            lambda *args, **kwargs: {"type": "product_question", "confidence": 0.99}
        )
        app_module.knowledge_answer_service.answer = lambda question: {
            "answer": "پاسخ ترکیبی تأییدشده",
            "matched_questions": ["ثبت سند", "کنترل موجودی"],
            "category": "حسابداری، انبار",
            "sources": [
                {"id": "faq:1", "title": "ثبت سند", "category": "حسابداری"},
                {"id": "doc:2", "title": "کنترل موجودی", "category": "انبار"},
            ],
            "answered_parts": ["ثبت سند", "کنترل موجودی"],
            "unanswered_parts": [],
        }
        response = self.client.post(
            "/ask",
            json={"question": "ثبت سند و کنترل موجودی را توضیح بده"},
        )
        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["answers"], ["پاسخ ترکیبی تأییدشده"])
        self.assertEqual(len(data["sources"]), 2)
        self.assertEqual(data["unanswered_parts"], [])


if __name__ == "__main__":
    unittest.main()
