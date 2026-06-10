import os
import deepl
from opencc import OpenCC
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_cc = OpenCC("s2twp")  # Simplified → Traditional Chinese (Taiwan)

# DeepL source lang mapping (settings code → DeepL API code)
_DEEPL_SOURCE: dict[str, str] = {
    "auto": None, "ja": "JA", "en": "EN", "ko": "KO",
    "zh": "ZH", "zh-tw": "ZH", "zh-cn": "ZH",
    "fr": "FR", "de": "DE", "es": "ES", "it": "IT",
    "pt": "PT", "ru": "RU", "ar": "AR", "tr": "TR",
}

# DeepL target lang mapping (settings code → DeepL API code)
_DEEPL_TARGET: dict[str, str] = {
    "zh-tw": "ZH", "zh-cn": "ZH", "zh": "ZH",
    "en": "EN-US", "ja": "JA", "ko": "KO",
    "fr": "FR", "de": "DE", "es": "ES", "it": "IT",
    "pt": "PT-PT", "ru": "RU", "tr": "TR",
}

_deepl_client: deepl.Translator | None = None
_deepl_api_key = os.getenv("DEEPL_API_KEY", "")
if _deepl_api_key:
    _deepl_client = deepl.Translator(_deepl_api_key)
    try:
        _usage = _deepl_client.get_usage()
        _used = _usage.character.count
        _limit = _usage.character.limit
        _remaining = _limit - _used
        print(f"[INFO] DeepL initialized: {_remaining:,} / {_limit:,} chars remaining ({_used/_limit*100:.1f}% used)")
        if _remaining < 100_000:
            print(f"[WARN] DeepL quota low! Only {_remaining:,} chars left, will fallback to SakuraLLM when exhausted")
    except Exception:
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


def _apply_opencc(text: str, target_lang: str) -> str:
    if target_lang.lower() == "zh-tw":
        return _cc.convert(text)
    return text


def _translate_deepl(text: str, source_lang: str, target_lang: str, context: str = "") -> str:
    src = _DEEPL_SOURCE.get(source_lang.lower())
    tgt = _DEEPL_TARGET.get(target_lang.lower(), target_lang.upper())
    result = _deepl_client.translate_text(
        text,
        source_lang=src,
        target_lang=tgt,
        context=context if context else None,
    )
    return _apply_opencc(str(result), target_lang)


def _translate_sakura(text: str, target_lang: str, context_ja: str = "", context_zh: str = "") -> str:
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
    return _apply_opencc(result, target_lang)


def _is_ja_to_zh(source_lang: str, target_lang: str) -> bool:
    return source_lang.lower() in ("ja", "auto") and target_lang.lower() in ("zh-tw", "zh-cn", "zh")


def translate(
    text: str,
    source_lang: str = "ja",
    target_lang: str = "zh-TW",
    context_ja: str = "",
    context_zh: str = "",
) -> str:
    if not text.strip():
        return ""

    if _deepl_client:
        try:
            return _translate_deepl(text, source_lang, target_lang, context=context_ja)
        except Exception as e:
            print(f"[WARN] DeepL error, falling back to SakuraLLM: {e}")

    if _is_ja_to_zh(source_lang, target_lang):
        try:
            return _translate_sakura(text, target_lang, context_ja, context_zh)
        except Exception as e:
            print(f"[WARN] SakuraLLM error: {e}")

    return ""
