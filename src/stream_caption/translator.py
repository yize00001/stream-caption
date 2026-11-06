import os
from dataclasses import dataclass
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
    "zh-tw": "ZH-HANT", "zh-cn": "ZH-HANS", "zh": "ZH",
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


@dataclass(frozen=True)
class TranslationResult:
    text: str = ""
    backend: str = "none"
    status: str = "unavailable"
    errors: tuple[str, ...] = ()


def _apply_opencc(text: str, target_lang: str) -> str:
    if target_lang.lower() == "zh-tw":
        return _cc.convert(text)
    return text


def _translate_deepl(text: str, source_lang: str, target_lang: str, context: str = "",
                     model_type: str = "default", glossary_id: str = "") -> str:
    src = _DEEPL_SOURCE.get(source_lang.lower())
    tgt = _DEEPL_TARGET.get(target_lang.lower(), target_lang.upper())
    options = {}
    if model_type != "default":
        options["model_type"] = model_type
    if glossary_id:
        options["glossary"] = glossary_id
    result = _deepl_client.translate_text(
        text,
        source_lang=src,
        target_lang=tgt,
        context=context if context else None,
        **options,
    )
    return _apply_opencc(str(result), target_lang)


def _translate_sakura(text: str, target_lang: str, context_ja: str = "", context_zh: str = "",
                      topic_context: str = "") -> TranslationResult:
    if context_ja and context_zh:
        content = (
            f"前句日文：{context_ja}\n"
            f"前句中文：{context_zh}\n\n"
            f"請翻譯以下日文（只輸出中文譯文）：{text}"
        )
    else:
        content = f"將以下日文翻譯成中文，只輸出譯文：{text}"

    topic_prefix = f"話題背景：{topic_context}\n\n" if topic_context else ""
    content = topic_prefix + content

    try:
        resp = _sakura_client.chat.completions.create(
            model=os.getenv("SAKURA_MODEL", "sakura"),
            messages=[{"role": "user", "content": content}],
            max_tokens=256,
            temperature=0.1,
        )
    except Exception as e:
        if context_ja and "context" in str(e).lower():
            print(f"[WARN] Context overflow, retrying without context ({type(e).__name__})")
            resp = _sakura_client.chat.completions.create(
                model=os.getenv("SAKURA_MODEL", "sakura"),
                messages=[{"role": "user", "content": topic_prefix + f"將以下日文翻譯成中文，只輸出譯文：{text}"}],
                max_tokens=256,
                temperature=0.1,
            )
        else:
            raise
    choice = resp.choices[0]
    if choice.finish_reason == "length":
        return TranslationResult(backend="sakura", status="truncated",
                                 errors=("sakura: output token limit reached",))
    result = (choice.message.content or "").strip()
    return TranslationResult(_apply_opencc(result, target_lang), "sakura",
                             "ok" if result else "empty")


def _is_ja_to_zh(source_lang: str, target_lang: str) -> bool:
    return source_lang.lower() == "ja" and target_lang.lower() in ("zh-tw", "zh-cn", "zh")


def translate_detailed(
    text: str,
    source_lang: str = "ja",
    target_lang: str = "zh-TW",
    context_source: str = "",
    context_target: str = "",
    model_type: str = "default",
    glossary_id: str = "",
    topic_context: str = "",
) -> TranslationResult:
    if not text.strip():
        return TranslationResult(status="empty_input")
    if source_lang.lower() == target_lang.lower():
        return TranslationResult(text, "identity", "ok")

    errors = []
    if _deepl_client:
        try:
            deepl_context = "\n".join(part for part in (topic_context, context_source) if part)
            result = _translate_deepl(text, source_lang, target_lang,
                                      context=deepl_context, model_type=model_type,
                                      glossary_id=glossary_id)
            if result.strip():
                return TranslationResult(result, "deepl", "ok")
            errors.append("deepl: empty response")
        except Exception as e:
            errors.append(f"deepl: {type(e).__name__}")
            print(f"[WARN] DeepL error: {type(e).__name__}")

    if _is_ja_to_zh(source_lang, target_lang):
        try:
            result = _translate_sakura(text, target_lang, context_source, context_target, topic_context)
            return TranslationResult(result.text, result.backend, result.status,
                                     tuple(errors) + result.errors)
        except Exception as e:
            errors.append(f"sakura: {type(e).__name__}")
            print(f"[WARN] SakuraLLM error: {type(e).__name__}")

    return TranslationResult(errors=tuple(errors))


def translate(text: str, source_lang: str = "ja", target_lang: str = "zh-TW",
              context_ja: str = "", context_zh: str = "") -> str:
    """Compatibility entry point for the CLI and existing callers."""
    return translate_detailed(text, source_lang, target_lang,
                              context_ja, context_zh).text
