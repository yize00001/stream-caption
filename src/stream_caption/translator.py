import os
import deepl
from opencc import OpenCC
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_cc = OpenCC("s2twp")  # Simplified → Traditional Chinese (Taiwan)

_deepl_client: deepl.Translator | None = None
_deepl_api_key = os.getenv("DEEPL_API_KEY", "")
if _deepl_api_key:
    _deepl_client = deepl.Translator(_deepl_api_key)
    print(f"[INFO] DeepL translator initialized")

_sakura_client = OpenAI(
    base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    api_key="ollama",
)


def _extract_first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _translate_deepl(text: str, context_ja: str = "") -> str:
    result = _deepl_client.translate_text(
        text,
        source_lang="JA",
        target_lang="ZH",
        context=context_ja if context_ja else None,
    )
    return _cc.convert(str(result))


def _translate_sakura(text: str, context_ja: str = "", context_zh: str = "") -> str:
    if context_ja and context_zh:
        content = (
            f"前句日文：{context_ja}\n"
            f"前句中文：{context_zh}\n\n"
            f"請翻譯以下日文（只輸出中文譯文）：{text}"
        )
    else:
        content = f"將以下日文翻譯成中文，只輸出譯文：{text}"

    try:
        resp = _sakura_client.chat.completions.create(
            model=os.getenv("SAKURA_MODEL", "sakura"),
            messages=[{"role": "user", "content": content}],
            max_tokens=256,
            temperature=0.1,
        )
        result = _extract_first_line(resp.choices[0].message.content or "")
    except Exception as e:
        if context_ja and "context" in str(e).lower():
            print(f"[WARN] Context overflow, retrying without context: {e}")
            resp = _sakura_client.chat.completions.create(
                model=os.getenv("SAKURA_MODEL", "sakura"),
                messages=[{"role": "user", "content": f"將以下日文翻譯成中文，只輸出譯文：{text}"}],
                max_tokens=256,
                temperature=0.1,
            )
            result = _extract_first_line(resp.choices[0].message.content or "")
        else:
            raise
    return _cc.convert(result)


def translate(text: str, context_ja: str = "", context_zh: str = "") -> str:
    if not text.strip():
        return ""

    if _deepl_client:
        try:
            return _translate_deepl(text, context_ja)
        except Exception as e:
            print(f"[WARN] DeepL error, falling back to SakuraLLM: {e}")

    try:
        return _translate_sakura(text, context_ja, context_zh)
    except Exception as e:
        print(f"[WARN] Translation error: {e}")
        return ""
