import json
import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv


load_dotenv()


class AIEngine:
    """Lazy, validated access to the language and embedding models."""

    def __init__(self) -> None:
        self.response_model = os.getenv("OPENAI_RESPONSE_MODEL", "gpt-5.6-luna")
        self.embedding_model_name = os.getenv(
            "EMBEDDING_MODEL",
            "paraphrase-multilingual-MiniLM-L12-v2",
        )
        self.timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
        self._openai_client = None
        self._embedding_model = None

    @property
    def enabled(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY", "").strip())

    def _get_client(self):
        if not self.enabled:
            return None
        if self._openai_client is None:
            from openai import OpenAI

            self._openai_client = OpenAI(
                api_key=os.getenv("OPENAI_API_KEY"),
                timeout=self.timeout_seconds,
            )
        return self._openai_client

    def _get_embedding_model(self):
        if self._embedding_model is None:
            from sentence_transformers import SentenceTransformer

            self._embedding_model = SentenceTransformer(self.embedding_model_name)
        return self._embedding_model

    @staticmethod
    def _parse_json_object(value: str) -> Optional[Dict[str, Any]]:
        text_value = str(value or "").strip()
        if not text_value:
            return None

        text_value = re.sub(r"^\x60\x60\x60(?:json)?\s*", "", text_value, flags=re.IGNORECASE)
        text_value = re.sub(r"\s*\x60\x60\x60$", "", text_value)
        try:
            parsed = json.loads(text_value)
            return parsed if isinstance(parsed, dict) else None
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

        start = text_value.find("{")
        end = text_value.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text_value[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def _complete(self, prompt: str) -> str:
        client = self._get_client()
        if client is None:
            return ""
        response = client.responses.create(model=self.response_model, input=prompt)
        return str(response.output_text or "").strip()

    def create_embeddings(self, texts: List[str]) -> List[Any]:
        clean_texts = [str(item or "").strip() for item in texts]
        if not clean_texts:
            return []
        embeddings = self._get_embedding_model().encode(
            clean_texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return list(embeddings)

    def create_embedding(self, text: str):
        embeddings = self.create_embeddings([text])
        return embeddings[0] if embeddings else []

    def similarity(self, question1: str, question2: str) -> float:
        from sklearn.metrics.pairwise import cosine_similarity

        emb1, emb2 = self.create_embeddings([question1, question2])
        return float(cosine_similarity([emb1], [emb2])[0][0])

    def analyze_question(self, question: str, category: Optional[str] = None):
        return {
            "question": question,
            "category": category,
            "intent": None,
            "confidence": 0,
            "use_ai": False,
        }

    def should_use_ai(self, confidence: float) -> bool:
        return confidence < 60

    def rewrite_question(self, question: str) -> Dict[str, Any]:
        fallback = {
            "rewritten_question": question,
            "intent": None,
            "confidence": 0.0,
        }
        if not self.enabled:
            return fallback
        prompt = f"""
تو فقط باید سؤال کاربر را برای جستجو در پایگاه دانش مدریک بازنویسی کنی.
- جواب سؤال را نده و چیزی حدس نزن.
- فقط منظور سؤال را شفاف و رسمی کن.
- اگر سؤال مبهم است، همان ابهام را حفظ کن.
- اصطلاحات اصلی کاربر را حذف نکن.

سؤال کاربر:
{question}

فقط JSON برگردان:
{{"rewritten_question":"...","intent":"...","confidence":0.0}}
"""
        try:
            result = self._parse_json_object(self._complete(prompt)) or {}
        except Exception:
            return fallback
        rewritten = str(result.get("rewritten_question") or question).strip()
        return {
            "rewritten_question": rewritten or question,
            "intent": result.get("intent"),
            "confidence": self._safe_float(result.get("confidence")),
        }

    def select_best_faq(
        self,
        original_question: str,
        candidates: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        fallback = {
            "selected_id": None,
            "confidence": 0.0,
            "reason": "ai_unavailable",
        }
        if not self.enabled or not candidates:
            return fallback
        candidate_text = "\n".join(
            f'{item.get("id", item.get("source_id"))}: '
            f'{item.get("question", item.get("title", ""))}'
            for item in candidates
        )
        prompt = f"""
وظیفه تو فقط انتخاب نزدیک‌ترین مورد از فهرست دانش مدریک است.
سؤال واقعی کاربر:
{original_question}

موارد پیشنهادی:
{candidate_text}

- جواب فنی تولید نکن و مورد جدید نساز.
- فقط یکی از IDهای داده‌شده را انتخاب کن.
- اگر اطلاعات کافی نیست selected_id را null بگذار.

فقط JSON برگردان:
{{"selected_id":null,"confidence":0.0,"reason":"..."}}
"""
        try:
            result = self._parse_json_object(self._complete(prompt)) or {}
        except Exception:
            return fallback
        return {
            "selected_id": result.get("selected_id"),
            "confidence": self._safe_float(result.get("confidence")),
            "reason": str(result.get("reason") or ""),
        }

    def decompose_question(self, question: str, max_parts: int = 4) -> List[str]:
        clean_question = str(question or "").strip()
        if not clean_question:
            return []
        if self.enabled:
            prompt = f"""
سؤال کاربر درباره نرم‌افزار مدریک را به پرسش‌های مستقل قابل جستجو تقسیم کن.
اگر سؤال فقط یک موضوع دارد، همان یک سؤال را برگردان.
حداکثر {max_parts} پرسش بساز. معنی، نام ماژول‌ها، خطاها و محدودیت‌ها را حفظ کن.
هیچ پاسخی تولید نکن و چیزی به سؤال اضافه نکن.

سؤال:
{clean_question}

فقط JSON برگردان:
{{"questions":["..."]}}
"""
            try:
                result = self._parse_json_object(self._complete(prompt)) or {}
                parts = self._unique_strings(result.get("questions") or [], max_parts)
                if parts:
                    return parts
            except Exception:
                pass

        parts = re.split(r"[؟?]+|\s+(?:همچنین|بعلاوه)\s+", clean_question)
        return self._unique_strings(parts, max_parts) or [clean_question]

    def compose_grounded_answer(
        self,
        question: str,
        subquestions: List[str],
        evidence: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not evidence:
            return self._empty_composition(subquestions)
        if not self.enabled:
            best = evidence[0]
            return {
                "answer": str(best.get("content") or "").strip(),
                "used_source_ids": [str(best.get("source_id"))],
                "answered_parts": subquestions[:1] or [question],
                "unanswered_parts": subquestions[1:],
                "confidence": self._safe_float(best.get("score")),
            }

        evidence_text = "\n\n".join(
            (
                f'SOURCE_ID: {item.get("source_id")}\n'
                f'TITLE: {item.get("title", "")}\n'
                f'CATEGORY: {item.get("category", "")}\n'
                f'CONTENT:\n{str(item.get("content") or "")[:6000]}'
            )
            for item in evidence
        )
        parts_text = "\n".join(f"- {item}" for item in subquestions)
        prompt = f"""
تو دستیار پشتیبانی مدریک هستی. فقط با شواهد زیر پاسخ بده.

سؤال اصلی:
{question}

بخش‌های سؤال:
{parts_text}

شواهد تأییدشده:
{evidence_text}

- هیچ اطلاعات، مسیر، عدد یا راه‌حلی خارج از شواهد اضافه نکن.
- بخش‌های قابل پاسخ را یک پاسخ منسجم و مرحله‌ای کن.
- بخش بدون شاهد را در unanswered_parts بگذار و حدس نزن.
- used_source_ids فقط باید شامل SOURCE_IDهای بالا باشد.
- اگر هیچ بخش قابل پاسخ نیست answer را خالی و confidence را صفر کن.

فقط JSON برگردان:
{{"answer":"...","used_source_ids":["faq:1"],"answered_parts":["..."],"unanswered_parts":["..."],"confidence":0.0}}
"""
        try:
            result = self._parse_json_object(self._complete(prompt)) or {}
        except Exception:
            return self._empty_composition(subquestions)
        return {
            "answer": str(result.get("answer") or "").strip(),
            "used_source_ids": self._unique_strings(
                result.get("used_source_ids") or [], 20
            ),
            "answered_parts": self._unique_strings(
                result.get("answered_parts") or [], 20
            ),
            "unanswered_parts": self._unique_strings(
                result.get("unanswered_parts") or [], 20
            ),
            "confidence": self._safe_float(result.get("confidence")),
        }

    def route_message(
        self,
        message: str,
        previous_question: str = "",
        previous_answer: str = "",
    ) -> Dict[str, Any]:
        fallback = self._route_message_offline(message, previous_answer)
        if not self.enabled:
            return fallback
        prompt = f"""
تو Router چت‌بات پشتیبانی مدریک هستی و فقط نوع پیام را تشخیص می‌دهی.

نوع پیام فقط یکی از این‌هاست:
- smalltalk: سلام، احوالپرسی، تشکر یا خداحافظی.
- product_question: سؤال درباره امکانات، خطاها، ماژول‌ها و محصولات مدریک.
- support_request: درخواست تیکت/انسان، دریافت‌نکردن پاسخ، یا حل‌نشدن مشکل پس از راه‌حل.
- clarification_request: کاربر پاسخ قبلی یا بخش مشخصی از آن را نفهمیده و توضیح ساده‌تر می‌خواهد. فقط با وجود پاسخ قبلی.
- unclear: هدف پیام واقعاً قابل تشخیص نیست.
- out_of_scope: سؤال نامرتبط با مدریک و پشتیبانی نرم‌افزار.

گفتن «قسمت ثبت سند را نفهمیدم» یا ادامه‌دادن درباره بخشی از پاسخ قبلی clarification_request است.
شرح یک خطای جدید product_question است. درخواست توضیح مجدد support_request نیست.

سؤال قبلی: {previous_question or "وجود ندارد"}
پاسخ قبلی: {previous_answer or "وجود ندارد"}
پیام جدید: {message}

فقط JSON برگردان:
{{"type":"product_question","confidence":0.0}}
"""
        try:
            result = self._parse_json_object(self._complete(prompt)) or {}
        except Exception:
            return fallback
        allowed_types = {
            "smalltalk",
            "product_question",
            "support_request",
            "clarification_request",
            "unclear",
            "out_of_scope",
        }
        message_type = str(result.get("type") or "")
        if message_type not in allowed_types:
            return fallback
        return {
            "type": message_type,
            "confidence": self._safe_float(result.get("confidence")),
        }

    def clarify_previous_answer(
        self,
        message: str,
        previous_question: str,
        previous_answer: str,
    ) -> str:
        if not self.enabled:
            return (
                f"حتماً. منظور پاسخ قبلی این بود:\n\n{previous_answer}\n\n"
                "دقیقاً کدام مرحله هنوز نامفهوم است؟"
            )
        prompt = f"""
تو دستیار پشتیبانی مدریک هستی. کاربر توضیح ساده‌ترِ پاسخ قبلی را می‌خواهد.
سؤال قبلی: {previous_question}
پاسخ قبلی: {previous_answer}
پیام جدید: {message}

- فقط همان پاسخ و بخش مورد اشاره کاربر را ساده و مرحله‌ای توضیح بده.
- اطلاعات جدید تولید نکن و چیزی حدس نزن.
- لینک، شماره، مسیر منو و عددهای مهم را تغییر نده.
- در پایان بپرس کدام بخش هنوز نامفهوم است.
"""
        try:
            reply = self._complete(prompt)
        except Exception:
            reply = ""
        return reply or previous_answer

    def generate_smalltalk_reply(self, message: str) -> str:
        if not self.enabled:
            return "سلام، در خدمتم. چه سؤالی درباره مدریک دارید؟"
        prompt = f"""
تو دستیار پشتیبانی مدریک هستی. به پیام روزمره کاربر کوتاه و دوستانه پاسخ بده.
وارد پاسخ فنی نشو و بحث را طولانی نکن.
پیام کاربر:
{message}
"""
        try:
            reply = self._complete(prompt)
        except Exception:
            reply = ""
        return reply or "سلام، در خدمتم. چه کمکی از دستم برمیاد؟"

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _unique_strings(values: Any, limit: int) -> List[str]:
        if not isinstance(values, list):
            return []
        result: List[str] = []
        seen = set()
        for value in values:
            clean_value = str(value or "").strip()
            key = clean_value.casefold()
            if not clean_value or key in seen:
                continue
            result.append(clean_value)
            seen.add(key)
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _empty_composition(subquestions: List[str]) -> Dict[str, Any]:
        return {
            "answer": "",
            "used_source_ids": [],
            "answered_parts": [],
            "unanswered_parts": subquestions,
            "confidence": 0.0,
        }

    @staticmethod
    def _route_message_offline(message: str, previous_answer: str) -> Dict[str, Any]:
        normalized = str(message or "").strip().casefold()
        support_words = ("تیکت", "پشتیبان", "حل نشد", "جواب نگرفتم", "پاسخ نگرفتم")
        clarification_words = (
            "نفهمید",
            "متوجه نشد",
            "منظورت",
            "ساده تر",
            "ساده‌تر",
            "کدوم قسمت",
        )
        smalltalk_words = ("سلام", "خداحافظ", "ممنون", "مرسی", "تشکر")
        if any(word in normalized for word in support_words):
            message_type = "support_request"
        elif previous_answer and any(word in normalized for word in clarification_words):
            message_type = "clarification_request"
        elif any(word in normalized for word in smalltalk_words) and len(normalized.split()) <= 8:
            message_type = "smalltalk"
        elif len(normalized) < 3:
            message_type = "unclear"
        else:
            message_type = "product_question"
        return {"type": message_type, "confidence": 0.55}


ai_engine = AIEngine()
