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


def _call_model(content: str) -> str:
    resp = _client.chat.completions.create(
        model=os.getenv("SAKURA_MODEL", "sakura"),
        messages=[{"role": "user", "content": content}],
        max_tokens=256,
        temperature=0.1,
    )
    return _extract_first_line(resp.choices[0].message.content or "")


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

        try:
            result = _call_model(content)
        except Exception as e:
            if context_ja and "context" in str(e).lower():
                # Context prompt exceeded model's n_ctx — retry without context
                print(f"[WARN] Context overflow, retrying without context: {e}")
                result = _call_model(f"將以下日文翻譯成中文，只輸出譯文：{text}")
            else:
                raise

        return _cc.convert(result)
    except Exception as e:
        print(f"[WARN] Translation error: {e}")
        return ""
