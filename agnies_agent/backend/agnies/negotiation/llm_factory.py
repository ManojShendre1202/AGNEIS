"""Single place that turns a "provider:model" spec into a real LangChain
chat client, and provides provider-aware structured-output binding/
parsing -- every LLM call site in this project (Prime, roles, executor,
ownership, review) goes through this instead of constructing
ChatGoogleGenerativeAI/ChatNVIDIA/ChatAnthropic directly, so switching
providers/models is a `.env` change, not a code change.

Model spec format is always "<provider>:<model id>", e.g.:
  "gemini:gemini-3.5-flash-lite"
  "nvidia:openai/gpt-oss-20b"
  "anthropic:claude-sonnet-5"
"""
import os


def parse_model_spec(spec: str) -> tuple[str, str]:
    provider, sep, model = spec.partition(":")
    if not sep:
        raise ValueError(
            f"model spec {spec!r} must be 'provider:model' (e.g. 'anthropic:claude-sonnet-5')"
        )
    return provider, model


def build_chat_model(spec: str, **kwargs):
    provider, model = parse_model_spec(spec)

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, google_api_key=os.environ["GEMINI_KEY"], **kwargs)

    if provider == "nvidia":
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
        return ChatNVIDIA(model=model, api_key=os.environ["NVIDIA_API_KEY"], timeout=300,
                           max_completion_tokens=16384, **kwargs)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, api_key=os.environ["ANTHROPIC_API_KEY"],
                              max_tokens=8192, **kwargs)

    raise ValueError(f"unknown provider {provider!r} in model spec {spec!r}")


def supports_prompt_caching(spec: str) -> bool:
    """Only Anthropic's cache_control content-block caching is wired up here.
    Gemini's explicit caching needs a paid, non-Lite model (see
    rate_limit.py's docstring history for why that's not usable on this
    project's free-tier Lite models); NVIDIA models used here haven't
    needed it."""
    provider, _ = parse_model_spec(spec)
    return provider == "anthropic"


def bind_structured(llm, schema: type, spec: str):
    provider, _ = parse_model_spec(spec)
    if provider == "nvidia":
        # NVIDIA's with_structured_output() drives Pydantic schemas through
        # guided_json/response_format extensions the hosted endpoint rejects
        # with a 400 (unknown field `guided_json`) -- forced tool-calling
        # via bind_tools/tool_choice is the one path that actually works.
        return llm.bind_tools([schema], tool_choice=schema.__name__)
    # Gemini and Anthropic both support with_structured_output cleanly.
    return llm.with_structured_output(schema, include_raw=True)


def parse_structured_result(raw, schema: type, spec: str):
    """Normalizes whatever bind_structured's chosen path returned into a
    plain (parsed, raw_message) pair, regardless of provider."""
    provider, _ = parse_model_spec(spec)
    if provider == "nvidia":
        tool_calls = getattr(raw, "tool_calls", None) or []
        if not tool_calls:
            content = getattr(raw, "content", None)
            raise RuntimeError(
                f"no tool_calls returned to parse {schema.__name__} from -- "
                f"model responded with plain content instead: {str(content)[:1000]!r}"
            )
        return schema.model_validate(tool_calls[0]["args"]), raw
    # Gemini/Anthropic: raw is the {"raw":..., "parsed":..., "parsing_error":...} dict
    if raw.get("parsing_error") is not None or raw.get("parsed") is None:
        raise RuntimeError(f"structured output parse failed for {schema.__name__}: {raw.get('parsing_error')!r}")
    return raw["parsed"], raw["raw"]


def cached_system_block(text: str, ttl: str = "1h") -> dict:
    """One cache_control-tagged content block for a stable prefix (e.g. a
    role's unchanging STATIC prompt tier, or an executor's already-written-
    files context) -- Anthropic bills the *first* call at normal input
    price and every subsequent call against the same prefix at ~10% of
    that, instead of paying full price to resend it every single time."""
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral", "ttl": ttl}}
