import os
from opencc import OpenCC
from dotenv import load_dotenv

_cc = OpenCC("s2twp")  # Simplified → Traditional Chinese (Taiwan)

load_dotenv()

# TRANSLATOR_BACKEND=sakura (local Ollama, default) or claude (Anthropic API)
_BACKEND = os.getenv("TRANSLATOR_BACKEND", "sakura").lower()

_SYSTEM_PROMPT = (
    "你是一個VTuber直播即時字幕翻譯模型，將日文翻譯成繁體中文（台灣用語）。"
    "規則：只輸出翻譯結果，一行，不加說明、括號或替代譯法。"
    "永遠使用繁體中文，禁止簡體字。"
    "保留角色名稱、直播用語、語氣。"
    "若有'Previous:'行，以此作為上下文判斷人稱代詞，只翻譯'Current:'行。"
)

_SYSTEM_PROMPT_CLAUDE = (
    "You are a subtitle translator for Japanese VTuber live streams. "
    "Translate the Japanese text to Traditional Chinese (繁體中文，台灣用語). "
    "Rules: "
    "1. Output ONLY the translated text — one single line. "
    "2. ALWAYS use Traditional Chinese characters. NEVER use Simplified Chinese. "
    "3. No alternatives, no parentheses, no explanations, no notes. "
    "4. Preserve character names, stream slang, and casual tone as-is. "
    "5. If a 'Previous:' line is provided, use it as context to determine "
    "correct subject/pronouns for the 'Current:' line. Translate only the Current line."
)


def _make_client():
    if _BACKEND == "sakura":
        from openai import OpenAI
        return OpenAI(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            api_key="ollama",
        )
    else:
        import anthropic
        return anthropic.Anthropic()


_client = _make_client()


def _extract_first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def translate(text: str, context: str = "") -> str:
    if not text.strip():
        return ""
    content = f"Previous: {context}\nCurrent: {text}" if context else text
    try:
        if _BACKEND == "sakura":
            user_msg = f"將以下日文翻譯成中文，只輸出譯文：{text}"
            resp = _client.chat.completions.create(
                model=os.getenv("SAKURA_MODEL", "sakura"),
                messages=[
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=150,
                temperature=0.1,
            )
            result = _extract_first_line(resp.choices[0].message.content or "")
            return _cc.convert(result)
        else:
            msg = _client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=128,
                system=_SYSTEM_PROMPT_CLAUDE,
                messages=[{"role": "user", "content": content}],
            )
            return _extract_first_line(msg.content[0].text)
    except Exception:
        return ""
