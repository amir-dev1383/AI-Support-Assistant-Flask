from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import os
import json

from openai import OpenAI
from dotenv import load_dotenv


load_dotenv()


class AIEngine:

    def __init__(self):
        self.enabled = True

        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY")
        )

        self.model = SentenceTransformer(
            "paraphrase-multilingual-MiniLM-L12-v2"
        )

    def create_embedding(self, text):
        return self.model.encode(
            text,
            normalize_embeddings=True
        )

    def similarity(self, question1, question2):
        emb1 = self.create_embedding(question1)
        emb2 = self.create_embedding(question2)

        score = cosine_similarity(
            [emb1],
            [emb2]
        )[0][0]

        return float(score)

    def analyze_question(self, question, category=None):
        return {
            "question": question,
            "category": category,
            "intent": None,
            "confidence": 0,
            "use_ai": False
        }

    def should_use_ai(self, confidence):
        return confidence < 60

    def rewrite_question(self, question):
        prompt = f"""
تو فقط باید سؤال کاربر را برای جستجو در پایگاه دانش مدریک بازنویسی کنی.

قوانین:
- جواب سؤال را نده.
- هیچ اطلاعات فنی جدیدی تولید نکن.
- چیزی حدس نزن.
- فقط منظور سؤال را شفاف و رسمی کن.
- اگر سؤال مبهم است، همان ابهام را حفظ کن.
- اصطلاحات اصلی کاربر را حذف نکن.

سؤال کاربر:
{question}

فقط JSON برگردان:
{{
  "rewritten_question": "...",
  "intent": "...",
  "confidence": 0.0
}}
"""

        response = self.client.responses.create(
            model="gpt-5.6-luna",
            input=prompt
        )

        text = response.output_text.strip()

        try:
            return json.loads(text)
        except Exception:
            return {
                "rewritten_question": question,
                "intent": None,
                "confidence": 0.0
            }

    def select_best_faq(self, original_question, candidates):
        candidate_text = "\n".join(
            [
                f'{item["id"]}: {item["question"]}'
                for item in candidates
            ]
        )

        prompt = f"""
وظیفه تو فقط انتخاب نزدیک‌ترین سؤال از فهرست FAQ مدریک است.

سؤال واقعی کاربر:
{original_question}

FAQهای پیشنهادی:
{candidate_text}

قوانین بسیار مهم:
- جواب فنی تولید نکن.
- هیچ FAQ جدیدی نساز.
- فقط از بین IDهای داده‌شده انتخاب کن.
- معنی واقعی سؤال کاربر مهم‌تر از شباهت کلمات است.
- اگر اطلاعات سؤال کاربر برای انتخاب دقیق کافی نیست، حدس نزن.
- اگر بین چند مورد مردد هستی، selected_id را null قرار بده.
- confidence فقط زمانی بالا باشد که تطابق معنایی واضح باشد.

فقط JSON برگردان:
{{
  "selected_id": null,
  "confidence": 0.0,
  "reason": "..."
}}
"""

        response = self.client.responses.create(
            model="gpt-5.6-luna",
            input=prompt
        )

        text = response.output_text.strip()

        try:
            return json.loads(text)
        except Exception:
            return {
                "selected_id": None,
                "confidence": 0.0,
                "reason": "invalid_ai_response"
            }


ai_engine = AIEngine()