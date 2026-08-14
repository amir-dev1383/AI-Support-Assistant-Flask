import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

model = os.getenv("OPENAI_MODEL", "gpt-5.5")

response = client.responses.create(
    model=model,
    input="""
تو دستیار پشتیبانی نرم‌افزار مدریک هستی.
فقط کوتاه و دقیق جواب بده.

سؤال تست:
اگر کاربر رمز عبور خود را فراموش کرد، چه باید بکند؟
"""
)

print(response.output_text)
