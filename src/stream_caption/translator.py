import os
from opencc import OpenCC
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_cc = OpenCC("s2twp")  # Simplified → Traditional Chinese (Taiwan)
_client = OpenAI(
    base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    api_key="ollama",
)


def _extract_first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def translate(text: str, context_ja: str = "", context_zh: str = "") -> str:
    if not text.strip():
        return ""
    try:
        if context_ja and context_zh:
            content = (
                f"前句日文：{context_ja}\n"
                f"前句中文：{context_zh}\n\n"
                f"請翻譯以下日文（只輸出中文譯文）：{text}"
            )
        else:
            content = f"將以下日文翻譯成中文，只輸出譯文：{text}"

        messages = [{"role": "user", "content": content}]

        resp = _client.chat.completions.create(
            model=os.getenv("SAKURA_MODEL", "sakura"),
            messages=messages,
            max_tokens=150,
            temperature=0.1,
        )
        result = _extract_first_line(resp.choices[0].message.content or "")
        return _cc.convert(result)
    except Exception:
        return ""
