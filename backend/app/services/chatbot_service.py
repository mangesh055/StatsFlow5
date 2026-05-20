"""
StatsFlow Agentic Chatbot Service
-----------------------------------
Integrates Groq/OpenAI-compatible chat APIs to provide:
  1. Conversational Q&A about the cleaned dataset
  2. Agentic command execution (drop rows, fill values, rename columns, etc.)

The LLM is injected with full dataset context (schema, stats, sample rows)
and instructed to respond in structured JSON for agentic operations.
"""

import json
import re
import asyncio
import difflib
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from app.config import settings
from app.utils.helpers import describe_dataframe, _convert_types, df_to_json_safe
import logging

try:
    from anthropic import AsyncAnthropic
except ImportError:  # pragma: no cover - optional runtime dependency
    AsyncAnthropic = None

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover - optional runtime dependency
    AsyncOpenAI = None

try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
except ImportError:  # pragma: no cover - optional runtime dependency
    ChatOpenAI = None
    AIMessage = None
    HumanMessage = None
    SystemMessage = None

try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover - optional runtime dependency
    genai = None

logger = logging.getLogger(__name__)

anthropic_client = None
openai_client = None
langchain_llm = None
gemini_model = None
openai_clients: Dict[str, Any] = {}


def _get_anthropic_client():
    """Initialize and cache Anthropic client lazily with clear failure reasons."""
    global anthropic_client

    if AsyncAnthropic is None:
        return None, "Anthropic SDK is not installed in the backend runtime environment."

    if not settings.anthropic_api_key:
        return None, "ANTHROPIC_API_KEY is missing in backend configuration."

    if anthropic_client is None:
        anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    return anthropic_client, None


def _get_openai_client(provider: str = "openai"):
    """Initialize and cache OpenAI-compatible clients lazily with clear failure reasons."""
    global openai_clients

    if AsyncOpenAI is None:
        return None, "OpenAI SDK is not installed in the backend runtime environment."

    provider_key = (provider or "openai").strip().lower()
    if provider_key == "groq":
        api_key = (settings.groq_api_key or "").strip()
        base_url = (settings.groq_base_url or "https://api.groq.com/openai/v1").strip()
        missing_message = "GROQ_API_KEY is missing in backend configuration."
    else:
        api_key = (settings.chat_api_key or "").strip()
        base_url = (settings.chat_base_url or "").strip()
        missing_message = "CHAT_API_KEY is missing in backend configuration."

    if not api_key:
        return None, missing_message

    if provider_key not in openai_clients:
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        openai_clients[provider_key] = AsyncOpenAI(**kwargs)

    return openai_clients[provider_key], None


def _get_langchain_llm():
    """Initialize and cache LangChain ChatOpenAI client lazily."""
    global langchain_llm

    if ChatOpenAI is None or SystemMessage is None or HumanMessage is None or AIMessage is None:
        return None, "LangChain dependencies are not installed (langchain, langchain-openai)."

    if not settings.chat_api_key and not settings.chat_base_url:
        return None, "CHAT_API_KEY (or CHAT_BASE_URL with a compatible gateway) is required for LangChain chat mode."

    if langchain_llm is None:
        kwargs = {
            "model": settings.chat_model,
            "temperature": 0.0,
            # Keep token budget bounded to avoid oversized-credit requests on gateways like OpenRouter.
            "max_tokens": 1024,
        }
        if settings.chat_api_key:
            kwargs["api_key"] = settings.chat_api_key
        if settings.chat_base_url:
            kwargs["base_url"] = settings.chat_base_url

        langchain_llm = ChatOpenAI(**kwargs)

    return langchain_llm, None


def _get_gemini_model():
    """Initialize and cache Gemini client lazily with clear failure reasons."""
    global gemini_model

    if genai is None:
        return None, "Gemini SDK is not installed. Please install google-generativeai."

    api_key = (settings.gemini_api_key or settings.chat_api_key or "").strip()
    if not api_key:
        return None, "GEMINI_API_KEY (or CHAT_API_KEY) is missing in backend configuration."

    if gemini_model is None:
        genai.configure(api_key=api_key)
        gemini_model = genai.GenerativeModel(settings.chat_model)

    return gemini_model, None


async def _invoke_gemini_chat(
    model,
    system_prompt: str,
    conversation_history: List[Dict[str, str]],
    message: str,
) -> Dict[str, Any]:
    """Invoke Gemini model and parse strict-JSON assistant output."""
    history_lines: List[str] = []
    for msg in (conversation_history or [])[-20:]:
        role = (msg.get("role") or "").strip().lower()
        content = (msg.get("content") or "").strip()
        if not role or not content:
            continue
        if role == "assistant":
            history_lines.append(f"assistant: {content}")
        else:
            history_lines.append(f"user: {content}")

    prompt = (
        f"{system_prompt}\n\n"
        "Conversation history:\n"
        + ("\n".join(history_lines) if history_lines else "(none)")
        + "\n\n"
        + f"Current user message:\n{message}\n\n"
        + "Return ONLY a valid JSON object."
    )

    def _run_generation():
        return model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.0,
                "max_output_tokens": 1024,
            },
        )

    response = await asyncio.to_thread(_run_generation)
    raw_content = (getattr(response, "text", None) or "").strip()

    if not raw_content:
        # Fallback extraction for SDK variants where .text is empty.
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            parts = getattr(candidates[0].content, "parts", []) if getattr(candidates[0], "content", None) else []
            raw_content = "\n".join([str(getattr(p, "text", "")) for p in parts]).strip()

    logger.info(f"Gemini raw response: {raw_content[:300]}...")
    return _parse_llm_response(raw_content)


def _coerce_llm_content(content: Any) -> str:
    """Normalize LangChain response content variants into plain text."""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        chunks = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    chunks.append(str(text))
            elif item is not None:
                chunks.append(str(item))
        return "\n".join(chunks)

    if content is None:
        return ""

    return str(content)


async def _invoke_langchain_chat(
    llm,
    system_prompt: str,
    conversation_history: List[Dict[str, str]],
    message: str,
) -> Dict[str, Any]:
    """Invoke LangChain chat model and parse strict-JSON assistant output."""
    lc_messages = [SystemMessage(content=system_prompt)]

    for msg in conversation_history:
        role = (msg.get("role") or "").strip().lower()
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant":
            lc_messages.append(AIMessage(content=content))
        elif role == "system":
            lc_messages.append(SystemMessage(content=content))
        else:
            lc_messages.append(HumanMessage(content=content))

    # CRITICAL: Ensure the current user message is being added
    logger.info(f"LangChain: Adding user message: {message[:100]}...")
    lc_messages.append(HumanMessage(content=message))
    logger.info(f"LangChain: Total messages in context: {len(lc_messages)}")

    response = await llm.ainvoke(lc_messages)
    raw_content = _coerce_llm_content(response.content).strip()
    logger.info(f"LangChain raw response: {raw_content[:300]}...")
    parsed = _parse_llm_response(raw_content)
    logger.info(f"LangChain parsed response type: {parsed.get('type')}")
    return parsed


def _friendly_chat_error(exc: Exception) -> str:
    """Map provider/runtime exceptions to concise user-facing messages."""
    raw = str(exc)
    lowered = raw.lower()

    # Handle explicit HTTP status codes first to avoid misclassification by keyword matches.
    if "error code: 429" in lowered or "'code': 429" in lowered or '"code":429' in lowered:
        if "temporarily rate-limited upstream" in lowered or ":free" in lowered:
            return (
                "This free model is temporarily rate-limited upstream on OpenRouter. "
                "Please retry in a moment, or switch to another model/provider."
            )
        return "AI provider rate limit reached. Please wait a moment and try again."

    if "error code: 401" in lowered or "'code': 401" in lowered or '"code":401' in lowered:
        return (
            "Chat authentication failed. Please verify CHAT_API_KEY (and CHAT_BASE_URL if used) in backend/.env and restart the backend."
        )

    # Surface common OpenRouter/provider routing issues explicitly.
    if "no endpoints found" in lowered or "no provider" in lowered:
        return (
            "No provider endpoint is currently available for the selected model or request constraints. "
            "Try again shortly, or switch CHAT_MODEL to another available OpenRouter model."
        )

    if "model" in lowered and any(k in lowered for k in ["not found", "does not exist", "unsupported"]):
        return (
            "The configured model appears invalid or unavailable for your API key/provider route. "
            "Please verify CHAT_MODEL in backend/.env."
        )

    if "context length" in lowered or "maximum context" in lowered or "prompt is too long" in lowered:
        return (
            "The request exceeded the model context/token limit. "
            "Please shorten the prompt or reduce conversation history."
        )

    if (
        "credit balance is too low" in lowered
        or "plans & billing" in lowered
        or "insufficient_quota" in lowered
        or "requires more credits" in lowered
        or "error code: 402" in lowered
        or "'code': 402" in lowered
    ):
        return (
            "Chat is currently unavailable because the AI provider account has insufficient credits. "
            "Please add credits in OpenRouter or reduce model/token usage."
        )

    if "invalid api key" in lowered or "authentication" in lowered or "401" in lowered:
        return (
            "Chat authentication failed. Please verify CHAT_API_KEY (and CHAT_BASE_URL if used) in backend/.env and restart the backend."
        )

    if "403" in lowered or "forbidden" in lowered:
        return (
            "Chat request was rejected by the provider (403 Forbidden). "
            "Check your OpenRouter key permissions and model access."
        )

    if "429" in lowered or "rate limit" in lowered or "too many requests" in lowered:
        return "AI provider rate limit reached. Please wait a moment and try again."

    if "timeout" in lowered or "timed out" in lowered or "gateway" in lowered or "502" in lowered or "503" in lowered or "504" in lowered:
        return "The upstream AI provider is temporarily unavailable (timeout/gateway error). Please try again shortly."

    return "Chat request failed due to an upstream AI service error. Please try again shortly."


def _resolve_column_name(requested: str, columns: List[str]) -> Optional[str]:
    """Resolve a user-provided column name to an existing column (case-insensitive)."""
    if not requested:
        return None

    requested_clean = requested.strip().strip('"\'')
    requested_clean = requested_clean.strip("<>()[]{}")
    requested_clean = re.sub(r"\s+", " ", requested_clean)
    if requested_clean in columns:
        return requested_clean

    requested_lower = requested_clean.lower()
    for col in columns:
        if col.lower() == requested_lower:
            return col
        if col.lower().replace("_", " ") == requested_lower:
            return col
        if col.lower().replace(" ", "_") == requested_lower:
            return col

    # Fuzzy contains match for requests like "customer id" vs "Customer_ID"
    for col in columns:
        normalized_col = re.sub(r"[_\s]+", "", col.lower())
        normalized_req = re.sub(r"[_\s]+", "", requested_lower)
        if normalized_req and (normalized_req in normalized_col or normalized_col in normalized_req):
            return col
    return None


def _schema_aware_query_rewrite(message: str, columns: List[str]) -> str:
    """Normalize free-form user query using lightweight NLP + schema-aware fuzzy matching.

    Goals:
    - tolerate spelling mistakes (emplyee, departmetn, experiance, etc.)
    - map fuzzy column mentions to exact DataFrame column names
    - normalize common shorthand like 'employee 115' -> 'employee id 115'
    """
    text = (message or "").strip()
    if not text:
        return text

    # 1) Common typo correction for query intent words.
    typo_map = {
        "emplyee": "employee",
        "employe": "employee",
        "departmetn": "department",
        "deparment": "department",
        "experiance": "experience",
        "expereince": "experience",
        "yar": "year",
        "yrs": "years",
        "salry": "salary",
        "performan": "performance",
        "querry": "query",
        "undersyand": "understand",
        "asky": "ask",
    }

    lowered = text.lower()
    for wrong, right in typo_map.items():
        lowered = re.sub(rf"\b{re.escape(wrong)}\b", right, lowered)

    # 2) Helpful structural rewrite for row-lookup style prompts.
    # Example: "employee 115" -> "employee id 115"
    lowered = re.sub(r"\bemployee\s+(\d+(?:\.\d+)?)\b", r"employee id \1", lowered)

    # 3) Schema-aware fuzzy mapping.
    # Build canonical forms for columns.
    col_norm_map: Dict[str, str] = {}
    for col in columns:
        variants = {
            col.lower(),
            col.lower().replace("_", " "),
            re.sub(r"[_\s]+", "", col.lower()),
        }
        for v in variants:
            col_norm_map[v] = col

    # Direct replacement for exact normalized aliases with boundaries.
    rewritten = lowered
    for alias, actual_col in sorted(col_norm_map.items(), key=lambda x: len(x[0]), reverse=True):
        if len(alias) < 3:
            continue
        pattern = rf"\b{re.escape(alias)}\b"
        rewritten = re.sub(pattern, actual_col, rewritten)

    # Fuzzy phrase matching on 1..3 token windows to recover typoed column names.
    tokens = re.findall(r"[a-zA-Z0-9_]+", rewritten)
    col_keys = list(col_norm_map.keys())
    max_replacements = 4
    replacements = 0

    if col_keys and tokens:
        for n in (3, 2, 1):
            if replacements >= max_replacements:
                break
            for i in range(0, len(tokens) - n + 1):
                phrase = " ".join(tokens[i:i + n]).strip()
                if len(phrase) < 3:
                    continue
                # Skip obvious non-column words.
                if phrase in {"with", "highest", "lowest", "tell", "what", "which", "is", "the", "for"}:
                    continue

                # lower cutoff to be more permissive for user phrasing
                close = difflib.get_close_matches(phrase, col_keys, n=1, cutoff=0.72)
                if not close:
                    continue

                target_col = col_norm_map[close[0]]
                rewritten_new = re.sub(rf"\b{re.escape(phrase)}\b", target_col, rewritten)
                if rewritten_new != rewritten:
                    rewritten = rewritten_new
                    replacements += 1
                    if replacements >= max_replacements:
                        break

    # Preserve trailing punctuation from original message when possible.
    if text and text[-1] in "?.!" and (not rewritten or rewritten[-1] not in "?.!"):
        rewritten += text[-1]

    return rewritten


def _build_local_summary(df: pd.DataFrame) -> str:
    """Generate a concise deterministic summary for local chat mode."""
    rows, cols = int(df.shape[0]), int(df.shape[1])
    missing = int(df.isnull().sum().sum())
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    categorical_cols = [c for c in df.columns if c not in numeric_cols]

    parts = [
        f"Dataset has {rows} rows and {cols} columns.",
        f"Total missing values: {missing}.",
        f"Numeric columns ({len(numeric_cols)}): {numeric_cols[:8]}",
        f"Categorical/date columns ({len(categorical_cols)}): {categorical_cols[:8]}",
    ]

    if numeric_cols:
        preview_stats = []
        for col in numeric_cols[:3]:
            series = df[col].dropna()
            if not series.empty:
                preview_stats.append(
                    f"{col}: mean={round(float(series.mean()), 3)}, min={round(float(series.min()), 3)}, max={round(float(series.max()), 3)}"
                )
        if preview_stats:
            parts.append("Quick numeric stats: " + " | ".join(preview_stats))

    return "\n".join(parts)


def _mentioned_columns(message: str, columns: List[str]) -> List[str]:
    """Return dataset columns referenced in user text (case-insensitive).
    
    Handles variations like:
    - "lights" matching "Lights" or "lighting_usage" or "Lighting Usage"
    - "energy consumption" matching "Energy_Consumption"
    """
    lowered = message.lower()
    matches = []
    
    for col in columns:
        col_lower = col.lower()
        col_space = col_lower.replace("_", " ")
        
        # Exact match (after lowercasing)
        if col_lower in lowered or col_space in lowered:
            matches.append(col)
        # Partial fuzzy match for compound words
        else:
            # Check if column words are all present in message  
            col_words = re.split(r'[_\s]+', col_lower)
            if len(col_words) > 1:
                # Check if all significant words from column are mentioned
                test_str = ' ' + lowered + ' '
                if all(f' {word} ' in test_str or f' {word}' in test_str for word in col_words if len(word) > 2):
                    matches.append(col)

    # Token-level fuzzy matching: try to match any short user token to column tokens
    try:
        tokens = re.findall(r"[a-zA-Z0-9_]+", message.lower())
        col_tokens_map = {}
        for col in columns:
            for part in re.split(r'[_\s]+', col.lower()):
                if len(part) > 2:
                    col_tokens_map.setdefault(part, set()).add(col)

        for t in tokens:
            if len(t) < 3:
                continue
            # direct token match
            if t in col_tokens_map:
                for c in col_tokens_map[t]:
                    if c not in matches:
                        matches.append(c)
                        continue
            # fuzzy match token to column token
            close = difflib.get_close_matches(t, list(col_tokens_map.keys()), n=1, cutoff=0.7)
            if close:
                for c in col_tokens_map.get(close[0], []):
                    if c not in matches:
                        matches.append(c)
    except Exception:
        pass
    
    return matches


def _extract_column_from_phrase(message_lower: str, columns: List[str]) -> Optional[str]:
    """Extract a column name from common prompt patterns like 'in <column>'."""
    
    # First, try to extract quoted column names like 'in "Energy Consumption"' or 'for "column_name"'
    quoted_patterns = [
        r'(?:in|for|of|on)\s+["\']([^"\']+)["\']',
        r'column\s+["\']([^"\']+)["\']',
    ]
    for pattern in quoted_patterns:
        match = re.search(pattern, message_lower)
        if match:
            candidate = match.group(1).strip()
            resolved = _resolve_column_name(candidate, columns)
            if resolved:
                return resolved
    
    # Then try unquoted patterns
    patterns = [
        r"(?:in|for|of|on)\s+(?:the\s+)?([a-zA-Z0-9_\-\s<>\[\]\(\){}]+?)(?:\s+column)?\s*(?:\?|\.|,|$)",
        r"column\s+([a-zA-Z0-9_\-\s<>\[\]\(\){}]+?)(?:\?|\.|,|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, message_lower)
        if not match:
            continue
        candidate = match.group(1).strip()
        resolved = _resolve_column_name(candidate, columns)
        if resolved:
            return resolved

    return None


def _parse_literal_value(raw: str) -> Any:
    """Parse user/model-provided scalar text into a typed Python value."""
    if raw is None:
        return None

    text = str(raw).strip().strip("`")
    if text == "":
        return None

    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1]

    lowered = text.lower()
    if lowered in {"null", "none", "na", "nan"}:
        return None
    if lowered in {"true", "false"}:
        return lowered == "true"

    # Try numeric coercion first.
    try:
        if re.fullmatch(r"[-+]?\d+", text):
            return int(text)
        if re.fullmatch(r"[-+]?\d*\.\d+", text):
            return float(text)
    except Exception:
        pass

    return text


def _build_follow_up_suggestions(df: pd.DataFrame, used_columns: Optional[List[str]] = None) -> List[str]:
    """Generate practical follow-up suggestions based on dataset schema and used columns."""
    columns = list(df.columns)
    numeric_cols = [c for c in columns if pd.api.types.is_numeric_dtype(df[c])]
    cat_cols = [c for c in columns if c not in numeric_cols]

    suggestions: List[str] = []
    metric = used_columns[0] if used_columns else (numeric_cols[0] if numeric_cols else None)

    if metric:
        suggestions.append(f"Show top 3 rows by {metric}")
        suggestions.append(f"What is the average of {metric}?")

    if metric and cat_cols:
        suggestions.append(f"Average {metric} by {cat_cols[0]}")

    id_col = next((c for c in columns if "id" in c.lower()), None)
    if id_col and metric:
        suggestions.append(f"What is {metric} for {id_col} 115?")

    return suggestions[:4]


def _build_response_meta(
    *,
    df: pd.DataFrame,
    columns_used: List[str],
    formula: str,
    filters: Optional[List[str]] = None,
    supporting_df: Optional[pd.DataFrame] = None,
    drilldown_title: str = "Supporting Rows",
) -> Dict[str, Any]:
    """Create unified response metadata for explain mode + drilldown + follow-up suggestions."""
    drill_df = supporting_df if supporting_df is not None else df.head(10)
    if not isinstance(drill_df, pd.DataFrame):
        drill_df = df.head(10)

    drill_rows = df_to_json_safe(drill_df, max_rows=20)
    drill_cols = list(drill_df.columns)

    return {
        "query_explain": {
            "formula": formula,
            "filters": filters or [],
            "columns_used": columns_used,
            "row_count": int(drill_df.shape[0]),
        },
        "drilldown": {
            "available": len(drill_rows) > 0,
            "title": drilldown_title,
            "columns": drill_cols,
            "rows": drill_rows,
        },
        "follow_up_suggestions": _build_follow_up_suggestions(df, used_columns=columns_used),
    }


def _try_compare_answer(message: str, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """Deterministically answer comparison queries like 'salary of 101 vs 120'."""
    lower = (message or "").lower().strip()
    if "compare" not in lower and " vs " not in lower:
        return None

    columns = list(df.columns)
    mentioned = _mentioned_columns(message, columns)
    numeric_cols = [c for c in columns if pd.api.types.is_numeric_dtype(df[c])]

    metric = next((c for c in mentioned if c in numeric_cols and "id" not in c.lower()), None)
    if metric is None:
        for hint in ["salary", "amount", "performance", "years", "experience", "score"]:
            if hint in lower:
                resolved = _resolve_column_name(hint, columns)
                if resolved and resolved in numeric_cols:
                    metric = resolved
                    break
    if metric is None:
        return None

    id_col = next((c for c in columns if "id" in c.lower()), None)
    values = re.findall(r"\b\d+(?:\.\d+)?\b", lower)
    if id_col and len(values) >= 2:
        a = float(values[0])
        b = float(values[1])
        id_series = pd.to_numeric(df[id_col], errors="coerce")
        row_a = df[id_series == a]
        row_b = df[id_series == b]
        if not row_a.empty and not row_b.empty:
            va = float(pd.to_numeric(row_a.iloc[0][metric], errors="coerce"))
            vb = float(pd.to_numeric(row_b.iloc[0][metric], errors="coerce"))
            diff = va - vb
            pct = (diff / vb * 100.0) if vb != 0 else None
            msg = (
                f"Comparison on {metric}: {id_col} {int(a) if a.is_integer() else a} = {va}, "
                f"{id_col} {int(b) if b.is_integer() else b} = {vb}. "
                f"Difference = {round(diff, 6)}"
            )
            if pct is not None:
                msg += f" ({round(pct, 2)}%)."
            else:
                msg += "."

            support = pd.concat([row_a.head(1), row_b.head(1)], ignore_index=True)
            return {
                "message": msg,
                "meta": _build_response_meta(
                    df=df,
                    columns_used=[metric, id_col],
                    formula=f"difference = {metric}(A) - {metric}(B); percentage = difference / {metric}(B)",
                    filters=[f"{id_col} in [{values[0]}, {values[1]}]"],
                    supporting_df=support,
                    drilldown_title="Compared Rows",
                ),
            }

    # Category-vs-category compare, e.g., Engineering vs Sales performance
    cat_cols = [c for c in columns if c not in numeric_cols]
    found_filter = _find_value_filter(df, lower)
    if found_filter and cat_cols:
        ccol = found_filter["column"]
        first_val = str(found_filter["value"])

        # Try to infer second category value from message tokens.
        all_vals = (
            df[ccol].dropna().astype(str).str.strip().unique().tolist()
            if ccol in df.columns else []
        )
        second_val = None
        for v in all_vals:
            if v.lower() != first_val.lower() and v.lower() in lower:
                second_val = v
                break

        if second_val:
            s1 = pd.to_numeric(df[df[ccol].astype(str).str.lower() == first_val.lower()][metric], errors="coerce").dropna()
            s2 = pd.to_numeric(df[df[ccol].astype(str).str.lower() == second_val.lower()][metric], errors="coerce").dropna()
            if not s1.empty and not s2.empty:
                m1 = float(s1.mean())
                m2 = float(s2.mean())
                diff = m1 - m2
                msg = (
                    f"Average {metric} comparison: {first_val} = {round(m1, 6)}, "
                    f"{second_val} = {round(m2, 6)}. "
                    f"Difference = {round(diff, 6)}."
                )
                support = df[df[ccol].astype(str).str.lower().isin([first_val.lower(), second_val.lower()])].head(20)
                return {
                    "message": msg,
                    "meta": _build_response_meta(
                        df=df,
                        columns_used=[metric, ccol],
                        formula=f"group average comparison on {metric}",
                        filters=[f"{ccol} in ['{first_val}', '{second_val}']"],
                        supporting_df=support,
                        drilldown_title="Comparison Group Rows",
                    ),
                }

    return None


def _try_what_if_simulation(message: str, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """Deterministically simulate what-if prompts without mutating source data."""
    lower = (message or "").lower().strip()
    if "if " not in lower and "what if" not in lower:
        return None

    change_match = re.search(
        r"(?:increase|increases|increased|decrease|decreases|decreased|up|down|raise|raises|raised|reduce|reduces|reduced)\s+(?:by\s+)?(\d+(?:\.\d+)?)\s*%",
        lower,
    )
    if not change_match:
        return None

    pct = float(change_match.group(1)) / 100.0
    is_decrease = any(k in lower for k in ["decrease", "down", "reduce"])
    multiplier = (1.0 - pct) if is_decrease else (1.0 + pct)

    columns = list(df.columns)
    metric = None
    for hint in ["salary", "amount", "price", "cost", "performance", "score", "total"]:
        if hint in lower:
            resolved = _resolve_column_name(hint, columns)
            if resolved and pd.api.types.is_numeric_dtype(df[resolved]):
                metric = resolved
                break
    if metric is None:
        numeric_cols = [c for c in columns if pd.api.types.is_numeric_dtype(df[c]) and "id" not in c.lower()]
        metric = numeric_cols[0] if numeric_cols else None
    if metric is None:
        return None

    working = df.copy()
    filters: List[str] = []
    filter_match = _find_value_filter(working, lower, exclude_columns=[metric])
    if filter_match:
        fcol = filter_match["column"]
        fval = filter_match["value"]
        mask = working[fcol].astype(str).str.strip().str.lower() == str(fval).strip().lower()
        filters.append(f"{fcol} = '{fval}'")
    else:
        mask = pd.Series(True, index=working.index)

    metric_series = pd.to_numeric(working[metric], errors="coerce")
    baseline = metric_series[mask].dropna()
    if baseline.empty:
        return None

    simulated = baseline * multiplier
    baseline_avg = float(baseline.mean())
    simulated_avg = float(simulated.mean())

    direction = "decrease" if is_decrease else "increase"
    msg = (
        f"What-if simulation ({direction} {round(pct * 100, 2)}%) on {metric}"
        + (f" with {filters[0]}" if filters else "")
        + f": baseline avg = {round(baseline_avg, 6)}, simulated avg = {round(simulated_avg, 6)}."
    )

    support = working.loc[mask].copy().head(20)
    if metric in support.columns:
        support[f"{metric}_simulated"] = pd.to_numeric(support[metric], errors="coerce") * multiplier

    return {
        "message": msg,
        "meta": _build_response_meta(
            df=df,
            columns_used=[metric] + ([filter_match["column"]] if filter_match else []),
            formula=f"simulated_{metric} = {metric} * {round(multiplier, 6)}; compare mean(simulated) vs mean(original)",
            filters=filters,
            supporting_df=support,
            drilldown_title="Simulation Supporting Rows",
        ),
    }


def _looks_like_follow_up(message: str) -> bool:
    """Heuristic to detect context-dependent follow-up prompts."""
    text = (message or "").strip().lower()
    if not text:
        return False

    starters = (
        "and ", "also ", "now ", "then ", "for that", "for this",
        "same ", "do the same", "what about", "again", "it ", "that ",
    )
    if any(text.startswith(s) for s in starters):
        return True

    pronouns = [" it", " that", "this", "those", "them", "previous"]
    if any(p in f" {text} " for p in pronouns) and len(text.split()) <= 14:
        return True

    return False


def _compose_contextual_follow_up_message(
    message: str,
    conversation_history: List[Dict[str, Any]],
) -> str:
    """Expand short follow-up prompts with recent context for local model handling."""
    if not _looks_like_follow_up(message):
        return message

    recent = []
    for item in reversed(conversation_history or []):
        role = (item.get("role") or "").strip().lower()
        content = (item.get("content") or "").strip()
        if not content or role not in {"user", "assistant"}:
            continue
        recent.append((role, content))
        if len(recent) >= 4:
            break

    if not recent:
        return message

    recent.reverse()
    context_lines = [f"{role}: {content}" for role, content in recent]
    return (
        "Conversation context:\n"
        + "\n".join(context_lines)
        + "\n\nCurrent user follow-up request:\n"
        + message
    )


def _coerce_value_for_series(series: pd.Series, value: Any) -> Any:
    """Best-effort type coercion for assigning/filtering against a column."""
    if value is None:
        return None

    if pd.api.types.is_numeric_dtype(series):
        try:
            if isinstance(value, (int, float, np.number)):
                return float(value)
            parsed = _parse_literal_value(value)
            return float(parsed)
        except (TypeError, ValueError):
            return value

    if pd.api.types.is_datetime64_any_dtype(series):
        try:
            return pd.to_datetime(value)
        except Exception:
            return value

    return str(value)


def _find_value_filter(
    df: pd.DataFrame,
    message_lower: str,
    exclude_columns: Optional[List[str]] = None,
    preferred_columns: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Find a simple equality filter by matching message text against categorical values.
    
    Prioritizes searching in preferred_columns first before searching all columns.
    """
    excluded = set(exclude_columns or [])
    preferred = set(preferred_columns or [])
    
    # Two-pass approach: first search preferred columns, then all columns
    column_search_order = []
    if preferred:
        column_search_order.extend([c for c in df.columns if c in preferred and c not in excluded])
    column_search_order.extend([c for c in df.columns if c not in excluded and c not in preferred])

    for col in column_search_order:
        if pd.api.types.is_numeric_dtype(df[col]):
            continue

        try:
            unique_values = (
                df[col]
                .dropna()
                .astype(str)
                .str.strip()
                .unique()
                .tolist()
            )
        except Exception:
            continue

        # Keep matching bounded and fast for high-cardinality columns.
        if len(unique_values) > 100:
            continue

        for raw_val in unique_values:
            value_lower = raw_val.lower().strip()
            if not value_lower or len(value_lower) < 2:
                continue

            if value_lower in message_lower:
                return {"column": col, "value": raw_val}

    return None


def _try_direct_aggregate_answer(message: str, df: pd.DataFrame) -> Optional[str]:
    """Compute exact aggregate answers ONLY for very specific, unambiguous prompts.
    
    This should only trigger for clear count/sum/avg questions with explicit numeric requests.
    Otherwise, let the LLM handle the response to ensure user context is respected.
    """
    lower = message.lower().strip()

    # Only trigger for VERY explicit aggregate keywords in combination
    # This prevents the function from intercepting complex questions
    has_explicit_count = any(phrase in lower for phrase in [
        "how many", "total count", "row count", "number of rows"
    ])
    has_explicit_sum = any(phrase in lower for phrase in [
        "total sum", "calculate total", "sum of"
    ])
    has_explicit_avg = any(phrase in lower for phrase in [
        "average of", "mean of"
    ])
    wants_sum = has_explicit_sum
    wants_avg = has_explicit_avg

    # Must have at least one explicit keyword AND be relatively short/simple
    has_aggregate_keyword = has_explicit_count or has_explicit_sum or has_explicit_avg
    if not has_aggregate_keyword or len(lower.split()) > 25:
        # Let the LLM handle complex questions
        return None

    mentioned = _mentioned_columns(message, list(df.columns))
    numeric_mentioned = [c for c in mentioned if pd.api.types.is_numeric_dtype(df[c])]
    categorical_mentioned = [c for c in mentioned if not pd.api.types.is_numeric_dtype(df[c])]

    target_col = None
    if numeric_mentioned:
        target_col = numeric_mentioned[0]
    elif df.select_dtypes(include=[np.number]).shape[1] == 1 and not has_explicit_count:
        target_col = df.select_dtypes(include=[np.number]).columns.tolist()[0]

    # Prioritize searching for filter values in mentioned categorical columns
    exclude_cols = [target_col] if target_col else None
    filter_match = _find_value_filter(
        df, 
        lower, 
        exclude_columns=exclude_cols,
        preferred_columns=categorical_mentioned if categorical_mentioned else None
    )
    working_df = df

    filter_text = ""
    if filter_match:
        filter_col = filter_match["column"]
        filter_val = filter_match["value"]
        working_df = df[
            df[filter_col].astype(str).str.strip().str.lower() == str(filter_val).strip().lower()
        ]
        filter_text = f" for rows where {filter_col} = '{filter_val}'"

    if has_explicit_count and target_col is None:
        row_count = int(working_df.shape[0])
        return f"The row count{filter_text} is {row_count}."

    if target_col is None:
        return None

    series = pd.to_numeric(working_df[target_col], errors="coerce")
    valid_n = int(series.notna().sum())

    if valid_n == 0:
        return f"I could not compute the value because '{target_col}' has no numeric values in the selected rows{filter_text}."

    if wants_avg and not wants_sum:
        value = float(series.mean())
        return (
            f"The average of '{target_col}'{filter_text} is {round(value, 6)} "
            f"(computed from {valid_n} numeric rows)."
        )

    value = float(series.sum())
    return (
        f"The total of '{target_col}'{filter_text} is {round(value, 6)} "
        f"(computed from {valid_n} numeric rows)."
    )


def _try_direct_extreme_row_answer(message: str, df: pd.DataFrame) -> Optional[str]:
    """Answer explicit max/min row lookups deterministically from the DataFrame.

    Example: "employee id with highest salary" -> returns Employee_ID + Salary.
    """
    lower = (message or "").lower().strip()
    if not lower or len(lower.split()) > 35:
        return None

    asks_highest = any(k in lower for k in ["highest", "maximum", "max", "top"])
    asks_lowest = any(k in lower for k in ["lowest", "minimum", "min", "least"])
    if not asks_highest and not asks_lowest:
        return None

    columns = list(df.columns)
    mentioned = _mentioned_columns(message, columns)
    numeric_mentioned = [c for c in mentioned if pd.api.types.is_numeric_dtype(df[c])]
    id_mentioned = [c for c in mentioned if "id" in c.lower()]

    # Prefer explicit metric terms over first-mentioned numeric columns.
    metric_hints = [
        "salary", "amount", "price", "cost", "total", "revenue", "income",
        "score", "performance", "years", "experience", "exp",
    ]

    target_numeric = None

    # 1) If the user explicitly mentioned a metric-like token, use it.
    for hint in metric_hints:
        if hint in lower:
            resolved = _resolve_column_name(hint, columns)
            if resolved and pd.api.types.is_numeric_dtype(df[resolved]):
                target_numeric = resolved
                break

    # 2) Try phrases like "highest <column>" / "max <column>".
    if target_numeric is None:
        phrase_patterns = [
            r"(?:highest|maximum|max|top|lowest|minimum|min|least)\s+([a-zA-Z0-9_\s]+)",
            r"with\s+(?:the\s+)?(?:highest|maximum|max|lowest|minimum|min|least)\s+([a-zA-Z0-9_\s]+)",
        ]
        for pattern in phrase_patterns:
            m = re.search(pattern, lower)
            if not m:
                continue
            candidate = m.group(1).strip().rstrip("?.!,")
            resolved = _resolve_column_name(candidate, columns)
            if resolved and pd.api.types.is_numeric_dtype(df[resolved]):
                target_numeric = resolved
                break

    # 3) Fallback to mentioned numeric columns, preferring non-ID fields.
    if target_numeric is None and numeric_mentioned:
        non_id_numeric = [c for c in numeric_mentioned if "id" not in c.lower()]
        target_numeric = non_id_numeric[0] if non_id_numeric else numeric_mentioned[0]

    if not target_numeric or target_numeric not in df.columns:
        return None

    id_col = id_mentioned[0] if id_mentioned else None
    if not id_col:
        for col in columns:
            if "id" in col.lower():
                id_col = col
                break
    # Determine which fields user wants from the extreme row.
    requested_output_cols: List[str] = []
    for col in mentioned:
        if col != target_numeric and col in df.columns and col not in requested_output_cols:
            requested_output_cols.append(col)

    # Robust fallback for common phrasing/typos like "emplyee" and explicit department asks.
    if "department" in lower:
        dept_col = _resolve_column_name("department", columns)
        if dept_col and dept_col not in requested_output_cols and dept_col != target_numeric:
            requested_output_cols.append(dept_col)

    if any(token in lower for token in ["employee", "emplyee", "id"]):
        if id_col and id_col not in requested_output_cols and id_col != target_numeric:
            requested_output_cols.append(id_col)

    if not requested_output_cols and id_col:
        requested_output_cols = [id_col]

    numeric_series = pd.to_numeric(df[target_numeric], errors="coerce")
    valid_mask = numeric_series.notna()
    if int(valid_mask.sum()) == 0:
        return f"I could not compute this because '{target_numeric}' has no valid numeric values."

    working = df.loc[valid_mask].copy()
    working["__metric__"] = pd.to_numeric(working[target_numeric], errors="coerce")

    if asks_highest and not asks_lowest:
        idx = working["__metric__"].idxmax()
        row = working.loc[idx]
        metric_val = float(row["__metric__"])
        if requested_output_cols:
            requested_parts = [f"{col} = {row[col]}" for col in requested_output_cols]
            return (
                f"For the highest {target_numeric} ({metric_val}), "
                + ", ".join(requested_parts)
                + "."
            )
        return f"The highest {target_numeric} is {metric_val}."

    idx = working["__metric__"].idxmin()
    row = working.loc[idx]
    metric_val = float(row["__metric__"])
    if requested_output_cols:
        requested_parts = [f"{col} = {row[col]}" for col in requested_output_cols]
        return (
            f"For the lowest {target_numeric} ({metric_val}), "
            + ", ".join(requested_parts)
            + "."
        )
    return f"The lowest {target_numeric} is {metric_val}."


def _try_direct_row_field_answer(message: str, df: pd.DataFrame) -> Optional[str]:
    """Answer exact row-field lookup queries deterministically.

    Examples:
    - "Years_Experience for Employee_ID 115"
    - "Tell me department of employee id 109"
    """
    lower = (message or "").lower().strip()
    if not lower or len(lower.split()) > 35:
        return None

    # Row-lookup should not trigger on ranking/group aggregate prompts.
    ranking_tokens = ["top", "highest", "maximum", "max", "lowest", "minimum", "min", "bottom", " by "]
    has_ranking_intent = any(tok in lower for tok in ranking_tokens)

    columns = list(df.columns)
    mentioned = _mentioned_columns(message, columns)
    if not mentioned:
        return None

    # Prefer ID-like column as the lookup key.
    key_col = next((c for c in mentioned if "id" in c.lower()), None)
    if not key_col:
        key_col = next((c for c in columns if "id" in c.lower()), None)
    if not key_col or key_col not in df.columns:
        return None

    # Requested output fields are mentioned columns other than key.
    output_cols = [c for c in mentioned if c != key_col and c in df.columns]

    # Add common fallback fields when users write natural language with typos.
    fallback_hints = [
        "department", "salary", "performance", "remote", "years", "experience", "exp",
    ]
    for hint in fallback_hints:
        if hint in lower:
            resolved = _resolve_column_name(hint, columns)
            if resolved and resolved != key_col and resolved not in output_cols:
                output_cols.append(resolved)

    if not output_cols:
        return None

    # Row lookup intent should mention a key reference explicitly.
    key_ref_tokens = [key_col.lower(), key_col.lower().replace("_", " "), "employee id", "id"]
    has_key_ref = any(tok in lower for tok in key_ref_tokens)
    if not has_key_ref:
        return None

    # Extract lookup value near key column reference first.
    key_pattern = re.escape(key_col).replace("\\_", "[_\\s]*")
    id_match = re.search(rf"\b{key_pattern}\b\s*(?:=|is|:)?\s*([a-zA-Z0-9_.-]+)", lower, flags=re.IGNORECASE)

    lookup_raw = None
    if id_match:
        candidate = id_match.group(1)
        # Ignore connector tokens accidentally captured by loose phrasing.
        if str(candidate).lower() not in {"with", "for", "of", "where", "whose", "that", "which"}:
            lookup_raw = candidate
    else:
        # Generic fallback: only use a trailing number for clear lookup prompts,
        # and avoid ranking/aggregate queries.
        if not has_ranking_intent:
            nums = re.findall(r"\b\d+(?:\.\d+)?\b", lower)
            if nums:
                lookup_raw = nums[-1]

    if lookup_raw is None:
        return None

    key_series = df[key_col]
    row = None

    if pd.api.types.is_numeric_dtype(key_series):
        try:
            if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", str(lookup_raw).strip()):
                return None
            lookup_num = float(lookup_raw)
            mask = pd.to_numeric(key_series, errors="coerce") == lookup_num
            if mask.any():
                row = df.loc[mask].iloc[0]
        except Exception:
            row = None

    if row is None:
        norm_key = key_series.astype(str).str.strip().str.lower()
        mask = norm_key == str(lookup_raw).strip().lower()
        if mask.any():
            row = df.loc[mask].iloc[0]

    if row is None:
        return f"I could not find any row where {key_col} = {lookup_raw}."

    values = [f"{col} = {row[col]}" for col in output_cols]
    return f"For {key_col} = {row[key_col]}, " + ", ".join(values) + "."


def _try_structured_query_answer(message: str, df: pd.DataFrame) -> Optional[str]:
    """Deterministic query planner for broad user questions.

    Supports:
    - top N by metric (with optional categorical filter)
    - aggregate metric (sum/avg/min/max/count)
    - grouped aggregate ("by <column>")
    """
    lower = (message or "").lower().strip()
    if not lower:
        return None

    columns = list(df.columns)
    mentioned = _mentioned_columns(message, columns)
    numeric_cols = [c for c in columns if pd.api.types.is_numeric_dtype(df[c])]

    def resolve_metric() -> Optional[str]:
        mentioned_numeric = [c for c in mentioned if c in numeric_cols]
        if mentioned_numeric:
            non_id_numeric = [c for c in mentioned_numeric if "id" not in c.lower()]
            return non_id_numeric[0] if non_id_numeric else mentioned_numeric[0]

        metric_hints = [
            "salary", "amount", "price", "cost", "total", "revenue", "income",
            "performance", "score", "years", "experience", "exp",
        ]
        for hint in metric_hints:
            if hint in lower:
                resolved = _resolve_column_name(hint, columns)
                if resolved and resolved in numeric_cols:
                    return resolved
        return None

    def resolve_group_col() -> Optional[str]:
        match = re.search(r"\bby\s+([a-zA-Z0-9_\s]+)", lower)
        if not match:
            return None
        candidate = match.group(1).strip().rstrip("?.!,")
        # Trim trailing fragments after common conjunctions.
        candidate = re.split(r"\b(where|with|for|having|whose|that)\b", candidate)[0].strip()
        resolved = _resolve_column_name(candidate, columns)
        return resolved

    # Optional categorical filter, e.g., "for marketing" or explicit value mention.
    metric_candidate = resolve_metric()
    filter_match = _find_value_filter(
        df,
        lower,
        exclude_columns=[metric_candidate] if metric_candidate else None,
        preferred_columns=[c for c in mentioned if c not in (metric_candidate or "")],
    )
    working_df = df
    filter_text = ""
    if filter_match:
        fcol = filter_match["column"]
        fval = filter_match["value"]
        working_df = df[
            df[fcol].astype(str).str.strip().str.lower() == str(fval).strip().lower()
        ]
        filter_text = f" where {fcol} = '{fval}'"

    # 1) Top/Bottom N by metric.
    top_match = re.search(r"\b(top|highest|maximum|max|lowest|minimum|min|bottom)\s*(\d+)?\b", lower)
    if top_match:
        metric = metric_candidate
        if metric:
            order_desc = top_match.group(1) in {"top", "highest", "maximum", "max"}
            n_raw = top_match.group(2)
            n = int(n_raw) if n_raw else 1
            n = max(1, min(n, 20))

            temp = working_df.copy()
            temp["__metric__"] = pd.to_numeric(temp[metric], errors="coerce")
            temp = temp[temp["__metric__"].notna()]
            if temp.empty:
                return f"I could not compute top/bottom values because '{metric}' has no valid numeric rows{filter_text}."

            temp = temp.sort_values("__metric__", ascending=not order_desc).head(n)

            output_cols = [c for c in mentioned if c != metric and c in temp.columns]
            if not output_cols:
                id_col = next((c for c in columns if "id" in c.lower()), None)
                if id_col and id_col in temp.columns:
                    output_cols = [id_col]

            lines = []
            for _, row in temp.iterrows():
                parts = [f"{metric}={float(row['__metric__'])}"]
                for col in output_cols[:3]:
                    parts.append(f"{col}={row[col]}")
                lines.append("- " + ", ".join(parts))

            title = "Top" if order_desc else "Bottom"
            return f"{title} {n} by {metric}{filter_text}:\n" + "\n".join(lines)

    # 2) Aggregate operations, with optional group-by.
    agg = None
    if any(k in lower for k in ["average", "mean", "avg"]):
        agg = "mean"
    elif any(k in lower for k in ["sum", "total"]):
        agg = "sum"
    elif any(k in lower for k in ["minimum", "lowest", "min"]):
        agg = "min"
    elif any(k in lower for k in ["maximum", "highest", "max"]):
        agg = "max"
    elif any(k in lower for k in ["count", "how many", "number of"]):
        agg = "count"

    if agg is None:
        return None

    group_col = resolve_group_col()
    metric = metric_candidate

    if agg == "count" and metric is None and group_col is None:
        return f"Row count{filter_text} is {int(working_df.shape[0])}."

    if metric is None and agg != "count":
        return None

    if group_col and group_col in working_df.columns:
        if agg == "count" and metric is None:
            grouped = working_df.groupby(group_col).size().sort_values(ascending=False)
            lines = [f"- {idx}: {int(val)}" for idx, val in grouped.head(20).items()]
            return f"Count by {group_col}{filter_text}:\n" + "\n".join(lines)

        metric_series = pd.to_numeric(working_df[metric], errors="coerce")
        temp = working_df.copy()
        temp["__metric__"] = metric_series
        temp = temp[temp["__metric__"].notna()]
        if temp.empty:
            return f"I could not compute {agg} because '{metric}' has no valid numeric rows{filter_text}."

        grouped = getattr(temp.groupby(group_col)["__metric__"], agg)().sort_values(ascending=False)
        lines = [f"- {idx}: {round(float(val), 6)}" for idx, val in grouped.head(20).items()]
        return f"{agg.upper()} of {metric} by {group_col}{filter_text}:\n" + "\n".join(lines)

    # Non-grouped aggregate.
    if agg == "count" and metric is not None:
        count_val = int(pd.to_numeric(working_df[metric], errors="coerce").notna().sum())
        return f"Count of valid '{metric}' values{filter_text} is {count_val}."

    series = pd.to_numeric(working_df[metric], errors="coerce").dropna()
    if series.empty:
        return f"I could not compute {agg} because '{metric}' has no valid numeric rows{filter_text}."

    value = getattr(series, agg)()
    return f"{agg.upper()} of '{metric}'{filter_text} is {round(float(value), 6)} (from {int(series.shape[0])} rows)."


def _highest_correlation_summary(df: pd.DataFrame) -> str:
    """Return strongest pairwise numeric correlations."""
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if len(numeric_cols) < 2:
        return "Not enough numeric columns to compute correlations."

    corr = df[numeric_cols].corr().abs()
    np.fill_diagonal(corr.values, np.nan)
    pairs = (
        corr.stack()
        .sort_values(ascending=False)
        .head(5)
    )
    if pairs.empty:
        return "Could not compute correlation pairs from the available data."

    lines = ["Top absolute correlations among numeric columns:"]
    seen = set()
    for (left, right), value in pairs.items():
        key = tuple(sorted([left, right]))
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {left} vs {right}: {round(float(value), 4)}")
        if len(lines) >= 6:
            break
    return "\n".join(lines)


def _numeric_averages_summary(df: pd.DataFrame) -> str:
    """Return means for all numeric columns."""
    numeric_df = df.select_dtypes(include=[np.number])
    if numeric_df.empty:
        return "There are no numeric columns to average."

    means = numeric_df.mean(numeric_only=True).sort_values(ascending=False)
    lines = ["Average (mean) for numeric columns:"]
    for col, value in means.items():
        lines.append(f"- {col}: {round(float(value), 4)}")
    return "\n".join(lines)


def _distribution_summary(df: pd.DataFrame, col: str) -> str:
    """Return a concise distribution summary for a single column."""
    series = df[col]
    missing = int(series.isnull().sum())

    if pd.api.types.is_numeric_dtype(series):
        clean = series.dropna()
        if clean.empty:
            return f"Column '{col}' has only missing values."
        q1, q2, q3 = clean.quantile([0.25, 0.5, 0.75]).tolist()
        return (
            f"Distribution for '{col}' ({series.dtype}): count={int(clean.shape[0])}, "
            f"mean={round(float(clean.mean()), 4)}, std={round(float(clean.std()), 4)}, "
            f"min={round(float(clean.min()), 4)}, Q1={round(float(q1), 4)}, "
            f"median={round(float(q2), 4)}, Q3={round(float(q3), 4)}, "
            f"max={round(float(clean.max()), 4)}, missing={missing}."
        )

    top = series.dropna().astype(str).value_counts().head(8)
    top_msg = ", ".join([f"{k} ({int(v)})" for k, v in top.items()]) if not top.empty else "no non-null values"
    return (
        f"Distribution for '{col}' ({series.dtype}): unique={int(series.nunique(dropna=True))}, "
        f"missing={missing}, top categories: {top_msg}."
    )


def _outlier_summary(df: pd.DataFrame) -> str:
    """Compute simple IQR-based outlier counts per numeric column."""
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if not numeric_cols:
        return "No numeric columns found, so outlier analysis is not available."

    rows = []
    for col in numeric_cols[:10]:
        clean = df[col].dropna()
        if clean.shape[0] < 4:
            continue
        q1, q3 = clean.quantile([0.25, 0.75]).tolist()
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        count = int(((clean < lower) | (clean > upper)).sum())
        pct = round((count / max(int(clean.shape[0]), 1)) * 100, 2)
        rows.append((col, count, pct))

    if not rows:
        return "Not enough numeric data to compute IQR-based outliers."

    rows.sort(key=lambda x: x[1], reverse=True)
    lines = ["Estimated remaining outliers (IQR rule):"]
    for col, count, pct in rows[:8]:
        lines.append(f"- {col}: {count} rows ({pct}%)")
    return "\n".join(lines)


def _insights_summary(df: pd.DataFrame) -> str:
    """Generate quick deterministic insights for exploratory prompts."""
    lines = []
    lines.append(f"1. Dataset size: {int(df.shape[0])} rows x {int(df.shape[1])} columns.")

    total_missing = int(df.isnull().sum().sum())
    lines.append(f"2. Total missing values: {total_missing}.")

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if numeric_cols:
        means = df[numeric_cols].mean(numeric_only=True)
        top_mean_col = means.sort_values(ascending=False).index[0]
        lines.append(f"3. Highest numeric average: {top_mean_col} = {round(float(means[top_mean_col]), 4)}.")
    else:
        lines.append("3. No numeric columns available for numeric trend insights.")

    lines.append("4. " + _highest_correlation_summary(df).replace("Top absolute correlations among numeric columns:\n", ""))
    lines.append("5. " + _outlier_summary(df).replace("Estimated remaining outliers (IQR rule):\n", ""))
    return "\n".join(lines)


def _column_quick_stats(df: pd.DataFrame, col: str) -> str:
    """Build quick descriptive stats for a specific column."""
    series = df[col]
    missing = int(series.isnull().sum())
    dtype = str(series.dtype)

    if pd.api.types.is_numeric_dtype(series):
        clean = series.dropna()
        if clean.empty:
            return f"Column '{col}' ({dtype}) has only missing values."

        return (
            f"Column '{col}' ({dtype}) summary: count={int(clean.shape[0])}, "
            f"mean={round(float(clean.mean()), 4)}, median={round(float(clean.median()), 4)}, "
            f"min={round(float(clean.min()), 4)}, max={round(float(clean.max()), 4)}, "
            f"missing={missing}."
        )

    value_counts = series.dropna().astype(str).value_counts().head(5)
    top_values = ", ".join([f"{k} ({int(v)})" for k, v in value_counts.items()]) if not value_counts.empty else "no non-null values"
    unique_count = int(series.nunique(dropna=True))
    return (
        f"Column '{col}' ({dtype}) summary: unique={unique_count}, missing={missing}, "
        f"top values: {top_values}."
    )


def _local_model_response(message: str, df: pd.DataFrame) -> Dict[str, Any]:
    """Rule-based local model that supports core analysis and cleaning actions."""
    columns = list(df.columns)
    lower = message.lower().strip()
    mentioned = _mentioned_columns(message, columns)

    if any(greet in lower for greet in ["hello", "hi", "hey", "hola"]):
        return {
            "type": "answer",
            "message": (
                "Local chat mode is active and ready. Ask things like: "
                "'summary', 'missing values', 'columns', 'stats for <column>', "
                "'top values in <column>', or cleaning commands."
            ),
        }

    if any(k in lower for k in ["column names", "list columns", "show columns", "what are the columns"]):
        return {
            "type": "answer",
            "message": f"Columns ({len(columns)}): {columns}",
        }

    if any(k in lower for k in ["how many rows", "row count", "how many columns", "shape", "dataset size"]):
        return {
            "type": "answer",
            "message": f"Dataset shape is {int(df.shape[0])} rows x {int(df.shape[1])} columns.",
        }

    if "missing" in lower or "null" in lower:
        if mentioned:
            pieces = []
            for col in mentioned[:3]:
                miss = int(df[col].isnull().sum())
                pct = round(float(df[col].isnull().mean() * 100), 2)
                pieces.append(f"{col}: {miss} missing ({pct}%)")
            return {
                "type": "answer",
                "message": "Missing-value report -> " + " | ".join(pieces),
            }

        total_missing = int(df.isnull().sum().sum())
        per_col = df.isnull().sum().sort_values(ascending=False).head(8)
        per_col_msg = ", ".join([f"{k}: {int(v)}" for k, v in per_col.items()])
        return {
            "type": "answer",
            "message": f"Total missing values: {total_missing}. Top columns with missing values: {per_col_msg}",
        }

    corr_match = re.search(r"correlation\s+(?:between\s+)?(.+?)\s+(?:and|,)\s+(.+)$", lower)
    if corr_match:
        left = _resolve_column_name(corr_match.group(1).strip(), columns)
        right = _resolve_column_name(corr_match.group(2).strip(), columns)
        if left and right:
            if left == right:
                return {"type": "answer", "message": "Correlation of a column with itself is 1.0."}
            if pd.api.types.is_numeric_dtype(df[left]) and pd.api.types.is_numeric_dtype(df[right]):
                subset = df[[left, right]].dropna()
                if subset.shape[0] < 2:
                    return {"type": "answer", "message": f"Not enough non-null rows to compute correlation between '{left}' and '{right}'."}
                corr = float(subset[left].corr(subset[right]))
                return {"type": "answer", "message": f"Correlation between '{left}' and '{right}' is {round(corr, 4)}."}
            return {"type": "answer", "message": f"Correlation requires numeric columns. '{left}' or '{right}' is non-numeric."}

    if any(k in lower for k in ["mean", "median", "min", "max", "std", "statistics", "stats"]):
        target_cols = mentioned[:2] if mentioned else []
        if not target_cols:
            extracted = _extract_column_from_phrase(lower, columns)
            if extracted:
                target_cols = [extracted]
        if target_cols:
            return {
                "type": "answer",
                "message": "\n".join([_column_quick_stats(df, col) for col in target_cols]),
            }

    if any(k in lower for k in ["top values", "most common", "frequent", "value counts", "unique values"]):
        target_cols = mentioned[:2] if mentioned else []
        if not target_cols:
            extracted = _extract_column_from_phrase(lower, columns)
            if extracted:
                target_cols = [extracted]
        if target_cols:
            return {
                "type": "answer",
                "message": "\n".join([_column_quick_stats(df, col) for col in target_cols]),
            }
        return {
            "type": "answer",
            "message": (
                "I could not resolve the column name for that top-values request. "
                f"Available columns are: {columns}"
            ),
        }

    if "correlation" in lower and any(k in lower for k in ["highest", "strongest", "top"]):
        return {
            "type": "answer",
            "message": _highest_correlation_summary(df),
        }

    if "average" in lower and any(k in lower for k in ["all numeric", "numeric columns", "all numbers", "all columns"]):
        return {
            "type": "answer",
            "message": _numeric_averages_summary(df),
        }

    if "distribution" in lower:
        target_col = mentioned[0] if mentioned else _extract_column_from_phrase(lower, columns)
        if target_col:
            return {
                "type": "answer",
                "message": _distribution_summary(df, target_col),
            }
        return {
            "type": "answer",
            "message": (
                "Please specify which column you want a distribution for. "
                f"Available columns: {columns}"
            ),
        }

    if "outlier" in lower:
        return {
            "type": "answer",
            "message": _outlier_summary(df),
        }

    if any(k in lower for k in ["top 5 insights", "top insights", "key insights", "main insights"]):
        return {
            "type": "answer",
            "message": _insights_summary(df),
        }

    if any(k in lower for k in ["summary", "overview", "describe", "dataset info", "health"]):
        return {
            "type": "answer",
            "message": _build_local_summary(df),
        }

    if "drop duplicate" in lower or "remove duplicate" in lower:
        return {
            "type": "action",
            "message": "Removing duplicate rows as requested.",
            "action": {"operation": "drop_duplicates", "params": {}},
        }

    delete_row_match = re.search(
        r"(?:delete|remove|drop)\s+(?:row|rows|record|records|entry|entries)\s+(?:where|for)?\s*(.+?)\s*(?:=|==|is|:)\s*(.+)$",
        lower,
    )
    if delete_row_match:
        where_requested = delete_row_match.group(1).strip()
        where_value = _parse_literal_value(delete_row_match.group(2).strip())
        where_col = _resolve_column_name(where_requested, columns)
        if where_col:
            return {
                "type": "action",
                "message": f"Deleting rows where '{where_col}' equals '{where_value}'.",
                "action": {
                    "operation": "delete_rows",
                    "params": {
                        "where_column": where_col,
                        "where_operator": "==",
                        "where_value": where_value,
                    },
                },
            }

    drop_null_match = re.search(r"drop\s+(?:null|missing)\s+rows?\s+(?:in|for)\s+(.+)$", lower)
    if drop_null_match:
        requested = drop_null_match.group(1).strip()
        col = _resolve_column_name(requested, columns)
        if col:
            return {
                "type": "action",
                "message": f"Dropping rows where '{col}' is null.",
                "action": {"operation": "drop_null_rows", "params": {"column": col}},
            }

    drop_col_match = re.search(r"drop\s+column\s+(.+)$", lower)
    if drop_col_match:
        requested = drop_col_match.group(1).strip()
        col = _resolve_column_name(requested, columns)
        if col:
            return {
                "type": "action",
                "message": f"Dropping column '{col}'.",
                "action": {"operation": "drop_column", "params": {"column": col}},
            }

    rename_match = re.search(r"rename\s+column\s+(.+?)\s+to\s+(.+)$", lower)
    if rename_match:
        old_requested = rename_match.group(1).strip()
        new_name = rename_match.group(2).strip().strip('"\'')
        old_name = _resolve_column_name(old_requested, columns)
        if old_name and new_name:
            return {
                "type": "action",
                "message": f"Renaming column '{old_name}' to '{new_name}'.",
                "action": {
                    "operation": "rename_column",
                    "params": {"old_name": old_name, "new_name": new_name},
                },
            }

    fill_match = re.search(
        r"fill\s+(?:missing\s+values?|nulls?)\s+(?:in|for)\s+(.+?)\s+(?:with|using)\s+(mean|median|mode)",
        lower,
    )
    if fill_match:
        requested = fill_match.group(1).strip()
        strategy = fill_match.group(2).strip()
        col = _resolve_column_name(requested, columns)
        if col:
            return {
                "type": "action",
                "message": f"Filling missing values in '{col}' using {strategy}.",
                "action": {
                    "operation": "fill_column",
                    "params": {"column": col, "strategy": strategy, "value": None},
                },
            }

    # update salary for employee id 109 to 180000
    set_where_match = re.search(
        r"(?:set|update|change|replace|modify|correct|revise)\s+(?:the\s+)?(.+?)\s+(?:for|where)\s+(.+?)\s*(?:=|==|is|:)\s*(.+?)\s+(?:to|=)\s+(.+)$",
        lower,
    )
    if set_where_match:
        target_requested = set_where_match.group(1).strip()
        where_requested = set_where_match.group(2).strip()
        where_value = _parse_literal_value(set_where_match.group(3).strip())
        new_value = _parse_literal_value(set_where_match.group(4).strip())
        target_col = _resolve_column_name(target_requested, columns)
        where_col = _resolve_column_name(where_requested, columns)
        if target_col and where_col:
            return {
                "type": "action",
                "message": (
                    f"Updating '{target_col}' to '{new_value}' for rows where "
                    f"'{where_col}' equals '{where_value}'."
                ),
                "action": {
                    "operation": "update_values",
                    "params": {
                        "target_column": target_col,
                        "new_value": new_value,
                        "where_column": where_col,
                        "where_operator": "==",
                        "where_value": where_value,
                    },
                },
            }

    # update salary to 90000 where department is sales
    set_where_match_alt = re.search(
        r"(?:set|update|change|replace|modify|correct|revise)\s+(?:the\s+)?(.+?)\s+(?:to|=)\s+(.+?)\s+for\s+(.+?)\s*(?:=|==|is|:)\s*(.+)$",
        lower,
    )
    if set_where_match_alt:
        target_requested = set_where_match_alt.group(1).strip()
        new_value = _parse_literal_value(set_where_match_alt.group(2).strip())
        where_requested = set_where_match_alt.group(3).strip()
        where_value = _parse_literal_value(set_where_match_alt.group(4).strip())
        target_col = _resolve_column_name(target_requested, columns)
        where_col = _resolve_column_name(where_requested, columns)
        if target_col and where_col:
            return {
                "type": "action",
                "message": (
                    f"Updating '{target_col}' to '{new_value}' for rows where "
                    f"'{where_col}' equals '{where_value}'."
                ),
                "action": {
                    "operation": "update_values",
                    "params": {
                        "target_column": target_col,
                        "new_value": new_value,
                        "where_column": where_col,
                        "where_operator": "==",
                        "where_value": where_value,
                    },
                },
            }

    # replace x with y in column
    replace_in_match = re.search(
        r"replace\s+(.+?)\s+with\s+(.+?)\s+(?:in|for)\s+(.+)$",
        lower,
    )
    if replace_in_match:
        old_value = _parse_literal_value(replace_in_match.group(1).strip())
        new_value = _parse_literal_value(replace_in_match.group(2).strip())
        requested = replace_in_match.group(3).strip()
        target_col = _resolve_column_name(requested, columns)
        if target_col:
            return {
                "type": "action",
                "message": f"Replacing '{old_value}' with '{new_value}' in '{target_col}'.",
                "action": {
                    "operation": "update_values",
                    "params": {
                        "target_column": target_col,
                        "old_value": old_value,
                        "new_value": new_value,
                    },
                },
            }

    return {
        "type": "answer",
        "message": (
            "I was unable to parse that request using the available analysis methods. "
            "Please try rephrasing your question more specifically. For example:\n"
            "- 'What is the average temperature?'\n"
            "- 'How many rows have humidity > 50?'\n"
            "- 'Show me statistics for the Energy Consumption column'\n"
            "- 'Drop all rows where Temperature is missing'"
        ),
    }

# ─────────────────────────────────────────────────────────────────────────────
# System Prompt Template
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """You are StatsFlow's AI Data Analyst — a friendly, precise assistant with complete access to the user's dataset. Your job is to understand what the user is asking in natural language and respond helpfully, even when the question is vague or uses informal phrasing.

## CORE PRINCIPLES
1. **Understand intent, not just keywords** — "give me the top earners", "who makes the most", "highest paid" all mean the same thing.
2. **Always answer with concrete numbers** from the dataset context. Never say "I cannot access the data."
3. **Be conversational** — short, clear answers beat long generic explanations.
4. **If something is ambiguous**, pick the most reasonable interpretation and answer it, then mention your assumption.
5. **For action requests**, confirm what you will do before listing the operation.
6. **IMPORTANT: You MUST return your response as a valid JSON object**.

## Dataset Context
{dataset_context}

## FEW-SHOT EXAMPLES (learn from these)

User: "give me a quick summary"
Response: {{"type": "answer", "message": "Here's a quick summary of your dataset:\\n- **Rows:** 500 | **Columns:** 8\\n- **Numeric columns:** Salary, Age, Performance_Score\\n- **Categorical columns:** Department, Job_Title, Remote_Work\\n- **Missing values:** 12 total (mostly in Performance_Score)\\n- **Top department:** Engineering (42% of records)"}}

User: "whats the avg salary"
Response: {{"type": "answer", "message": "The average salary is **$72,450** (computed from 498 non-null rows)."}}

User: "show me anyone earning more than 100k"
Response: {{"type": "answer", "message": "There are **23 employees** with Salary > 100,000. Top earners:\\n- Employee 201: $145,000 (Engineering)\\n- Employee 88: $138,500 (Management)\\n- Employee 312: $125,000 (Data Science)"}}

User: "drop rows where salary is empty"
Response: {{"type": "action", "message": "I'll remove all rows where Salary is null.", "reason": "User explicitly requested deletion of rows with missing Salary values.", "confidence": 0.92, "action": {{"operation": "drop_null_rows", "params": {{"column": "Salary"}}}}}}

User: "what's interesting about this data"
Response: {{"type": "answer", "message": "Here are a few notable patterns I found:\\n1. **Salary skew**: The salary distribution is right-skewed — a few high earners pull the mean above the median.\\n2. **Top department**: Engineering accounts for 42% of all employees.\\n3. **Strong correlation**: Years_Experience and Salary have a correlation of 0.78 — more experience clearly predicts higher pay.\\n4. **Missing data**: Performance_Score has 8 missing values — you may want to fill or drop these before analysis."}}

User: "rename the dept column to Department"
Response: {{"type": "action", "message": "Renaming 'dept' to 'Department'.", "reason": "User requested a column rename.", "confidence": 0.96, "action": {{"operation": "rename_column", "params": {{"old_name": "dept", "new_name": "Department"}}}}}}

## Response Format (STRICT JSON — NO EXCEPTIONS)
Always respond with exactly one JSON object:

### Answering a question:
{{"type": "answer", "message": "Your answer here. Use **bold** for key numbers. Use bullet lists for multiple items."}}

### Executing an action:
{{"type": "action", "message": "Plain-English explanation of what you're doing.", "reason": "Why this action is appropriate.", "confidence": 0.0-1.0, "action": {{"operation": "<operation_name>", "params": {{...}}}}}}

## Available Operations
- `drop_null_rows`: params: {{"column": "col_name"}}
- `drop_duplicates`: params: {{}}
- `fill_column`: params: {{"column": "col_name", "strategy": "mean|median|mode|value", "value": <optional>}}
- `drop_column`: params: {{"column": "col_name"}}
- `rename_column`: params: {{"old_name": "old", "new_name": "new"}}
- `filter_rows`: params: {{"column": "col_name", "operator": ">|<|>=|<=|==|!=", "value": <value>}}
- `update_values`: params: {{"target_column": "col", "new_value": <val>, "where_column": <optional>, "where_operator": "==", "where_value": <optional>}}
- `delete_rows`: params: {{"where_column": "col", "where_operator": "==", "where_value": <val>}}

## Rules
1. ONLY respond with valid JSON — no markdown fences, no preamble, no extra text outside the JSON
2. NEVER say "I cannot access the data" — you have full column profiles in the dataset context above
3. NEVER fabricate row-level values not present in the context
4. For vague requests like "summarize", "tell me about", "what's interesting" → give a rich `answer` drawing from the column profiles
5. If a column name is misspelled or informal, match it to the closest real column and proceed
6. Keep answers concise — 3-6 bullet points or 2-3 sentences for most questions
"""


async def chat_with_dataset(
    message: str,
    df: pd.DataFrame,
    conversation_history: List[Dict[str, str]],
) -> Tuple[str, Optional[Dict], Optional[pd.DataFrame], Optional[Dict[str, Any]]]:
    """
    Process a user message in the context of the cleaned dataset.

    Args:
        message: The user's input message.
        df: The current state of the cleaned DataFrame.
        conversation_history: List of previous {role, content} message dicts.

    Returns:
        Tuple of:
          - response_message (str): Natural language response to show the user
          - action_performed (dict | None): The action that was executed, if any
          - updated_df (DataFrame | None): Modified DataFrame if an action was taken
                    - response_meta (dict | None): Explain/drilldown/follow-up metadata for UI
    """
    logger.info(f"[CHAT] User message: {message}")
    try:
        effective_message = _compose_contextual_follow_up_message(
            message=message,
            conversation_history=conversation_history,
        )

        normalized_message = _schema_aware_query_rewrite(effective_message, list(df.columns))
        if normalized_message != effective_message:
            logger.info(f"[CHAT] Normalized query: '{effective_message}' -> '{normalized_message}'")
        effective_message = normalized_message

        compare_pack = _try_compare_answer(message=effective_message, df=df)
        if compare_pack is not None:
            logger.info("[CHAT] Returning deterministic compare answer")
            return compare_pack["message"], None, None, compare_pack.get("meta")

        what_if_pack = _try_what_if_simulation(message=effective_message, df=df)
        if what_if_pack is not None:
            logger.info("[CHAT] Returning deterministic what-if answer")
            return what_if_pack["message"], None, None, what_if_pack.get("meta")

        direct_row_field = _try_direct_row_field_answer(message=effective_message, df=df)
        if direct_row_field is not None:
            logger.info("[CHAT] Returning direct row-field answer")
            meta = _build_response_meta(
                df=df,
                columns_used=_mentioned_columns(effective_message, list(df.columns)),
                formula="row lookup by key column",
                filters=[],
                supporting_df=df.head(10),
                drilldown_title="Supporting Rows",
            )
            return direct_row_field, None, None, meta

        direct_structured = _try_structured_query_answer(message=effective_message, df=df)
        if direct_structured is not None:
            logger.info("[CHAT] Returning direct structured-query answer")
            meta = _build_response_meta(
                df=df,
                columns_used=_mentioned_columns(effective_message, list(df.columns)),
                formula="deterministic structured query (aggregate/groupby/top-k/filter)",
                filters=[],
                supporting_df=df.head(20),
                drilldown_title="Structured Query Supporting Rows",
            )
            return direct_structured, None, None, meta

        direct_extreme = _try_direct_extreme_row_answer(message=effective_message, df=df)
        if direct_extreme is not None:
            logger.info("[CHAT] Returning direct extreme-row answer")
            meta = _build_response_meta(
                df=df,
                columns_used=_mentioned_columns(effective_message, list(df.columns)),
                formula="argmax/argmin row selection",
                filters=[],
                supporting_df=df.head(20),
                drilldown_title="Extreme Value Supporting Rows",
            )
            return direct_extreme, None, None, meta

        direct_aggregate = _try_direct_aggregate_answer(message=effective_message, df=df)
        if direct_aggregate is not None:
            logger.info(f"[CHAT] Returning direct aggregate answer")
            meta = _build_response_meta(
                df=df,
                columns_used=_mentioned_columns(effective_message, list(df.columns)),
                formula="deterministic aggregate calculation",
                filters=[],
                supporting_df=df.head(20),
                drilldown_title="Aggregate Supporting Rows",
            )
            return direct_aggregate, None, None, meta

        # If this appears to be a data-analytics question and deterministic handlers
        # could not parse it, do not risk speculative answers from the LLM.
        if _is_analytics_query(effective_message, df):
            logger.info("[CHAT] Analytics intent detected but deterministic parsing failed; returning guided clarification")
            return (
                _build_guided_clarification(effective_message, df),
                None,
                None,
                _build_response_meta(
                    df=df,
                    columns_used=_mentioned_columns(effective_message, list(df.columns)),
                    formula="clarification requested before deterministic computation",
                    filters=[],
                    supporting_df=df.head(10),
                    drilldown_title="Available Data Preview",
                ),
            )

        provider = (settings.chat_provider or "groq").strip().lower()
        logger.info(f"[CHAT] Using provider: {provider}")
        parsed = None

        if provider in ["groq", "auto"]:
            client, unavailable_reason = _get_openai_client("groq")
            if client is not None:
                try:
                    logger.info("[CHAT] Calling Groq API")
                    dataset_context = _build_dataset_context(df)
                    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                        dataset_context=json.dumps(dataset_context, indent=2)
                    )

                    # Only keep role and content to prevent API errors for unsupported properties like 'action' and 'meta'
                    messages = [{"role": msg.get("role"), "content": msg.get("content")} for msg in conversation_history]
                    messages.append({"role": "user", "content": effective_message})

                    response = await client.chat.completions.create(
                        model=settings.chat_model,
                        max_tokens=1024,
                        temperature=0.0,
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": system_prompt},
                            *messages,
                        ],
                    )

                    raw_content = (response.choices[0].message.content or "").strip()
                    logger.info(f"[CHAT] Groq raw response: {raw_content[:300]}...")
                    parsed = _parse_llm_response(raw_content)
                    logger.info("[CHAT] Groq returned successfully")
                except Exception as exc:
                    logger.error(f"[CHAT] Groq error: {exc}")
                    if provider == "groq":
                        raise
                    logger.warning(
                        "Auto chat mode fallback: Groq request failed (%s). Trying other remote providers.",
                        str(exc),
                    )
            else:
                if provider == "groq":
                    logger.error(f"[CHAT] Groq unavailable: {unavailable_reason}")
                    return (
                        f"Chat service is unavailable. {unavailable_reason}",
                        None,
                        None,
                        None,
                    )

        if provider in ["langchain", "auto"]:
            llm, unavailable_reason = _get_langchain_llm()
            if llm is not None:
                try:
                    logger.info(f"[CHAT] Calling LangChain LLM")
                    dataset_context = _build_dataset_context(df)
                    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                        dataset_context=json.dumps(dataset_context, indent=2)
                    )
                    parsed = await _invoke_langchain_chat(
                        llm=llm,
                        system_prompt=system_prompt,
                        conversation_history=conversation_history,
                        message=effective_message,
                    )
                    logger.info(f"[CHAT] LangChain returned successfully")
                except Exception as exc:
                    logger.error(f"[CHAT] LangChain error: {exc}")
                    if provider == "langchain":
                        raise
                    logger.warning(
                        "Auto chat mode fallback: LangChain request failed (%s). Trying other remote providers.",
                        str(exc),
                    )
            else:
                if provider == "langchain":
                    logger.error(f"[CHAT] LangChain unavailable: {unavailable_reason}")
                    return (
                        f"Chat service is unavailable. {unavailable_reason}",
                        None,
                        None,
                        None,
                    )

        if provider in ["openai", "auto"]:
            client, unavailable_reason = _get_openai_client()
            if client is not None:
                try:
                    logger.info(f"[CHAT] Calling OpenAI-compatible API")
                    dataset_context = _build_dataset_context(df)
                    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                        dataset_context=json.dumps(dataset_context, indent=2)
                    )

                    # Only keep role and content to prevent API errors for unsupported properties like 'action' and 'meta'
                    messages = [{"role": msg.get("role"), "content": msg.get("content")} for msg in conversation_history]
                    messages.append({"role": "user", "content": effective_message})

                    # OpenAI-compatible APIs generally expect system in the messages list.
                    response = await client.chat.completions.create(
                        model=settings.chat_model,
                        max_tokens=1024,
                        temperature=0.0,
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": system_prompt},
                            *messages,
                        ],
                    )

                    raw_content = (response.choices[0].message.content or "").strip()
                    logger.info(f"[CHAT] OpenAI raw response: {raw_content[:300]}...")
                    parsed = _parse_llm_response(raw_content)
                    logger.info(f"[CHAT] OpenAI returned successfully")
                except Exception as exc:
                    logger.error(f"[CHAT] OpenAI error: {exc}")
                    if provider == "openai":
                        raise
                    logger.warning(
                        "Auto chat mode fallback: OpenAI-compatible request failed (%s). Trying other remote providers.",
                        str(exc),
                    )
            else:
                if provider == "openai":
                    logger.error(f"[CHAT] OpenAI unavailable: {unavailable_reason}")
                    return (
                        f"Chat service is unavailable. {unavailable_reason}",
                        None,
                        None,
                    )

        elif provider == "anthropic":
            # Legacy provider path retained for backward compatibility.
            client, unavailable_reason = _get_anthropic_client()
            if client is None:
                logger.error(f"[CHAT] Anthropic unavailable: {unavailable_reason}")
                return (
                    f"Chat service is unavailable. {unavailable_reason}",
                    None,
                    None,
                    None,
                )

            dataset_context = _build_dataset_context(df)
            system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                dataset_context=json.dumps(dataset_context, indent=2)
            )

            # Only keep role and content to prevent API errors for unsupported properties like 'action' and 'meta'
            messages = [{"role": msg.get("role"), "content": msg.get("content")} for msg in conversation_history]
            messages.append({"role": "user", "content": effective_message})

            response = await client.messages.create(
                model=settings.chat_model,
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
            )

            raw_content = response.content[0].text.strip()
            logger.info(f"[CHAT] Anthropic raw response: {raw_content[:300]}...")
            parsed = _parse_llm_response(raw_content)

        if parsed is None:
            if provider == "local":
                logger.warning("[CHAT] LLM returned None, using local mode")
                parsed = _local_model_response(message=effective_message, df=df)
            else:
                logger.error("[CHAT] No remote provider produced a valid response")
                return (
                    "Chat service is unavailable. No remote model returned a valid response. "
                    "Verify GROQ_API_KEY/CHAT_API_KEY, CHAT_PROVIDER, and CHAT_MODEL in backend/.env.",
                    None,
                    None,
                    None,
                )

        if parsed.get("type") == "answer" and _looks_vague_response(parsed.get("message", "")):
            logger.warning("[CHAT] Vague answer detected")
            direct_aggregate = _try_direct_aggregate_answer(message=effective_message, df=df)
            if direct_aggregate is not None:
                parsed = {"type": "answer", "message": direct_aggregate}
            else:
                parsed = {
                    "type": "answer",
                    "message": _build_guided_clarification(message=effective_message, df=df),
                }

        # Safety net for model template replies: force a concrete computed value when possible.
        response_preview = (parsed.get("message") or "").lower()
        if parsed.get("type") == "answer" and any(k in response_preview for k in ["**x**", "replace x", "tbd", "placeholder"]):
            direct_aggregate = _try_direct_aggregate_answer(message=effective_message, df=df)
            if direct_aggregate is not None:
                parsed = {"type": "answer", "message": direct_aggregate}

        response_type = parsed.get("type", "answer")
        response_message = parsed.get("message", "I couldn't process that request.")
        action_performed = None
        updated_df = None
        response_meta: Optional[Dict[str, Any]] = None

        logger.info(f"[CHAT] Final response type: {response_type}")

        if response_type == "action":
            action = parsed.get("action", {})
            operation = action.get("operation", "")
            params = action.get("params", {})

            # Execute the agentic action on the DataFrame
            updated_df, action_result = _execute_action(df, operation, params)
            computed_confidence = _action_confidence(operation, action_result)
            model_confidence = parsed.get("confidence")
            if isinstance(model_confidence, (int, float)):
                confidence_score = max(0.0, min(1.0, float(model_confidence)))
            else:
                confidence_score = computed_confidence

            explainability = parsed.get("reason") or _action_explainability(operation, params, action_result)
            action_performed = {
                "operation": operation,
                "params": params,
                "result": action_result,
                "confidence_score": round(float(confidence_score), 2),
                "confidence_label": _confidence_label(float(confidence_score)),
                "explainability": explainability,
                "requires_approval": True,
            }

            # Append the action result to the message
            response_message += f"\n\n**Action Result:** {action_result}"

            response_meta = _build_response_meta(
                df=updated_df if isinstance(updated_df, pd.DataFrame) else df,
                columns_used=[c for c in [params.get("column"), params.get("target_column"), params.get("where_column")] if c],
                formula=f"agentic operation: {operation}",
                filters=[
                    f"{params.get('where_column')} {params.get('where_operator')} {params.get('where_value')}"
                    for _ in [0]
                    if params.get("where_column") and params.get("where_operator") is not None and params.get("where_value") is not None
                ],
                supporting_df=(updated_df if isinstance(updated_df, pd.DataFrame) else df).head(20),
                drilldown_title="Action Result Rows",
            )
        else:
            response_meta = _build_response_meta(
                df=df,
                columns_used=_mentioned_columns(effective_message, list(df.columns)),
                formula="LLM answer grounded on dataset context",
                filters=[],
                supporting_df=df.head(20),
                drilldown_title="Supporting Rows",
            )

        return response_message, action_performed, updated_df, response_meta

    except Exception as exc:
        logger.error(f"Chatbot error: {exc}")
        return (
            _friendly_chat_error(exc),
            None,
            None,
            None,
        )


def _build_dataset_context(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Build a focused JSON context object describing the dataset.
    Injected into the system prompt so the LLM has full situational awareness.

    Design goals:
    - Compact enough not to crowd out the user's question in the prompt window
    - Rich enough to answer stat/aggregate questions without extra DB calls
    - Column profiles cover the FULL dataset (not just samples)
    """
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    categorical_cols = [c for c in df.columns if c not in numeric_cols]
    total_rows = max(int(df.shape[0]), 1)
    missing_total = int(df.isnull().sum().sum())

    # Dynamically scale verbosity based on column count to avoid exceeding LLM context window/TPM limits.
    num_cols = int(df.shape[1])
    is_wide = num_cols > 25

    # --- Top-level summary (always short) ---
    summary = {
        "rows": total_rows,
        "columns": num_cols,
        "missing_cells": missing_total,
        "numeric_columns": numeric_cols,
        "categorical_columns": categorical_cols,
    }

    # --- Column profiles (compact per-column stats) ---
    column_profiles: Dict[str, Any] = {}
    for col in df.columns:
        series = df[col]
        missing_count = int(series.isnull().sum())
        profile: Dict[str, Any] = {
            "dtype": str(series.dtype),
            "missing": missing_count,
        }
        if not is_wide:
            profile["missing_pct"] = round(missing_count / total_rows * 100, 1)

        if col in numeric_cols:
            clean = pd.to_numeric(series, errors="coerce").dropna()
            if not clean.empty:
                profile["mean"] = round(float(clean.mean()), 4)
                profile["min"] = round(float(clean.min()), 4)
                profile["max"] = round(float(clean.max()), 4)
                if not is_wide:
                    profile["median"] = round(float(clean.median()), 4)
                    profile["std"] = round(float(clean.std()), 4) if len(clean) > 1 else 0.0
        else:
            # For categoricals, include fewer top values if wide
            top_k = 2 if is_wide else 5
            vc = series.dropna().astype(str).str.strip().value_counts().head(top_k)
            profile["unique"] = int(series.nunique(dropna=True))
            profile["top_values"] = [
                {"value": str(k), "count": int(v)}
                for k, v in vc.items()
            ]

        column_profiles[col] = profile

    # --- Top correlations (compact, only for numeric pairs) ---
    correlations: List[str] = []
    if len(numeric_cols) >= 2 and not is_wide:
        try:
            corr_matrix = df[numeric_cols].corr().abs()
            np.fill_diagonal(corr_matrix.values, np.nan)
            pairs = corr_matrix.stack().sort_values(ascending=False).head(5)
            seen: set = set()
            for (a, b), v in pairs.items():
                key = tuple(sorted([a, b]))
                if key in seen:
                    continue
                seen.add(key)
                correlations.append(f"{a} vs {b}: {round(float(v), 3)}")
                if len(correlations) >= 4:
                    break
        except Exception:
            pass

    # --- Sample rows (reduce sample count for wide datasets) ---
    try:
        sample_count = 1 if num_cols > 50 else (2 if is_wide else 5)
        sample_rows = df_to_json_safe(df, max_rows=sample_count)
    except Exception:
        sample_rows = []

    return {
        "summary": summary,
        "column_profiles": column_profiles,
        "top_correlations": correlations,
        "sample_rows": sample_rows,
        "note": "Column profiles are computed across the COMPLETE dataset, not just samples.",
    }


def _parse_llm_response(raw: str) -> Dict[str, Any]:
    """
    Safely parse the LLM's JSON response, stripping any accidental markdown fences.

    Args:
        raw: Raw string from the LLM.

    Returns:
        Parsed dict, or a default answer dict if parsing fails.
    """
    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first and last fence lines
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse LLM JSON. Raw: {raw[:200]}")
        return {"type": "answer", "message": cleaned}


def _action_confidence(operation: str, result_text: str) -> float:
    if "failed" in (result_text or "").lower() or "not found" in (result_text or "").lower():
        return 0.40

    mapping = {
        "drop_duplicates": 0.92,
        "drop_null_rows": 0.88,
        "fill_column": 0.84,
        "drop_column": 0.82,
        "rename_column": 0.96,
        "filter_rows": 0.86,
        "delete_rows": 0.88,
        "update_values": 0.78,
    }
    return mapping.get(operation, 0.70)


def _confidence_label(score: float) -> str:
    if score >= 0.90:
        return "high"
    if score >= 0.75:
        return "medium"
    return "low"


def _action_explainability(operation: str, params: Dict[str, Any], result_text: str) -> str:
    operation_title = operation.replace("_", " ") if operation else "data update"
    param_pairs = [f"{k}={v}" for k, v in (params or {}).items() if v is not None]
    param_text = ", ".join(param_pairs[:4])
    if param_text:
        return f"AI executed '{operation_title}' using {param_text}. Result: {result_text}"
    return f"AI executed '{operation_title}'. Result: {result_text}"


def _looks_vague_response(message: str) -> bool:
    """Detect generic responses that are likely not grounded in dataset evidence."""
    text = (message or "").strip().lower()
    if not text:
        return True

    vague_markers = [
        "it depends",
        "generally",
        "typically",
        "as an ai",
        "without the data",
        "cannot access",
        "i don't have access",
    ]
    return any(marker in text for marker in vague_markers)


def _build_guided_clarification(message: str, df: pd.DataFrame) -> str:
    """Return a helpful clarification prompt with schema-aware examples."""
    columns = list(df.columns)
    numeric_cols = [c for c in columns if pd.api.types.is_numeric_dtype(df[c])]
    id_col = next((c for c in columns if "id" in c.lower()), None)
    cat_cols = [c for c in columns if c not in numeric_cols]

    examples: List[str] = []
    if id_col and numeric_cols:
        examples.append(f"- What is {numeric_cols[0]} for {id_col} 115?")
    if numeric_cols:
        examples.append(f"- Which record has highest {numeric_cols[0]}?")
        examples.append(f"- Average {numeric_cols[0]} by {cat_cols[0]}" if cat_cols else f"- Average {numeric_cols[0]}")
    if cat_cols:
        examples.append(f"- Top 3 rows where {cat_cols[0]} = <value> by {numeric_cols[0] if numeric_cols else columns[0]}")

    cols_preview = columns[:12]
    cols_text = ", ".join(cols_preview) + (" ..." if len(columns) > len(cols_preview) else "")
    examples_text = "\n".join(examples[:4]) if examples else "- Ask about any column shown below"

    return (
        "I can answer that, but I need a slightly clearer metric or filter.\n"
        f"Available columns: {cols_text}\n"
        "Try one of these patterns:\n"
        f"{examples_text}"
    )


def _is_analytics_query(message: str, df: pd.DataFrame) -> bool:
    """Heuristic to detect dataframe-analytics intent.

    IMPORTANT: Only return True when the query is VERY specific and structured
    enough that a clarification is genuinely needed. For open-ended / exploratory
    questions we prefer to let the LLM answer rather than returning a guidance wall.
    """
    lower = (message or "").lower().strip()
    if not lower:
        return False

    # Never block greetings, meta-questions, or exploratory prompts
    open_ended_markers = [
        "tell me", "describe", "explain", "summarize", "summary", "overview",
        "insights", "interesting", "anything", "what can", "help me", "hello",
        "hi ", "hey ", "what is", "show me", "give me", "find", "analyze",
        "analysis", "explore", "understand", "recommend", "suggest",
    ]
    if any(m in lower for m in open_ended_markers):
        return False

    # Only intercept when user clearly wants a specific numeric result but
    # doesn't name a column — a case where clarification genuinely helps.
    specific_no_column = (
        any(t in lower for t in ["how many", "sum of", "total of", "average of", "mean of"])
        and not _mentioned_columns(message, list(df.columns))
    )
    return specific_no_column


def _execute_action(
    df: pd.DataFrame,
    operation: str,
    params: Dict[str, Any],
) -> Tuple[pd.DataFrame, str]:
    """
    Execute a named data manipulation operation on the DataFrame.

    Args:
        df: Current DataFrame.
        operation: Operation name string.
        params: Operation parameters dict.

    Returns:
        Tuple of (updated_df, result_description_string)
    """
    updated_df = df.copy()

    try:
        logger.info(f"Executing action: {operation} with params: {params}")
        operation_aliases = {
            "update_value": "update_values",
            "replace_value": "update_values",
            "replace_values": "update_values",
            "set_value": "update_values",
            "set_values": "update_values",
            "edit_values": "update_values",
        }
        operation = operation_aliases.get(operation, operation)

        if operation == "drop_null_rows":
            col = params.get("column")
            if col and col in updated_df.columns:
                before = len(updated_df)
                updated_df = updated_df.dropna(subset=[col])
                removed = before - len(updated_df)
                result = f"Dropped {removed} rows where '{col}' was null. {len(updated_df)} rows remain."
            else:
                result = f"Column '{col}' not found. Available: {list(df.columns)}"

        elif operation == "delete_rows":
            where_col = params.get("where_column")
            where_operator = str(params.get("where_operator", "==")).strip()
            where_value = params.get("where_value", None)

            if where_col and where_col in updated_df.columns:
                before = len(updated_df)
                where_series = updated_df[where_col]
                typed_where_value = _coerce_value_for_series(where_series, where_value)
                op_map = {
                    "==": where_series == typed_where_value,
                    "!=": where_series != typed_where_value,
                    ">": where_series > typed_where_value,
                    "<": where_series < typed_where_value,
                    ">=": where_series >= typed_where_value,
                    "<=": where_series <= typed_where_value,
                }
                if where_operator not in op_map:
                    result = f"Invalid where_operator '{where_operator}'."
                else:
                    updated_df = updated_df.loc[~op_map[where_operator]].copy()
                    removed = before - len(updated_df)
                    result = (
                        f"Deleted {removed} rows where '{where_col}' {where_operator} {where_value}. "
                        f"{len(updated_df)} rows remain."
                    )
            else:
                result = f"Column '{where_col}' not found. Available: {list(df.columns)}"

        elif operation == "drop_duplicates":
            before = len(updated_df)
            updated_df = updated_df.drop_duplicates()
            removed = before - len(updated_df)
            result = f"Removed {removed} duplicate rows. {len(updated_df)} rows remain."

        elif operation == "fill_column":
            col = params.get("column")
            strategy = params.get("strategy", "value")
            value = params.get("value")

            if col and col in updated_df.columns:
                missing_count = int(updated_df[col].isnull().sum())
                if strategy == "mean":
                    fill_val = updated_df[col].mean()
                elif strategy == "median":
                    fill_val = updated_df[col].median()
                elif strategy == "mode":
                    mode_result = updated_df[col].mode()
                    fill_val = mode_result[0] if not mode_result.empty else value
                else:
                    fill_val = value

                updated_df[col].fillna(fill_val, inplace=True)
                result = f"Filled {missing_count} missing values in '{col}' with {fill_val} (strategy: {strategy})."
            else:
                result = f"Column '{col}' not found."

        elif operation == "drop_column":
            col = params.get("column")
            if col and col in updated_df.columns:
                updated_df = updated_df.drop(columns=[col])
                result = f"Successfully dropped column '{col}'. Remaining columns: {list(updated_df.columns)}"
            else:
                result = f"Column '{col}' not found."

        elif operation == "rename_column":
            old_name = params.get("old_name")
            new_name = params.get("new_name")
            if old_name and old_name in updated_df.columns and new_name:
                updated_df = updated_df.rename(columns={old_name: new_name})
                result = f"Renamed column '{old_name}' to '{new_name}'."
            else:
                result = f"Could not rename: '{old_name}' not found or new name invalid."

        elif operation == "filter_rows":
            col = params.get("column")
            operator = params.get("operator", "==")
            value = params.get("value")

            if col and col in updated_df.columns and value is not None:
                before = len(updated_df)
                op_map = {
                    ">": updated_df[col] > value,
                    "<": updated_df[col] < value,
                    ">=": updated_df[col] >= value,
                    "<=": updated_df[col] <= value,
                    "==": updated_df[col] == value,
                    "!=": updated_df[col] != value,
                }
                if operator in op_map:
                    updated_df = updated_df[op_map[operator]]
                    result = (
                        f"Filtered to {len(updated_df)} rows where "
                        f"'{col}' {operator} {value} (removed {before - len(updated_df)} rows)."
                    )
                else:
                    result = f"Invalid operator '{operator}'."
            else:
                result = "Filter failed — check column name and value."

        elif operation == "update_values":
            target_requested = params.get("target_column") or params.get("column")
            target_col = _resolve_column_name(str(target_requested or ""), list(updated_df.columns))
            if not target_col:
                result = (
                    f"Target column '{target_requested}' not found. "
                    f"Available: {list(updated_df.columns)}"
                )
            else:
                new_value = params.get("new_value")
                old_value = params.get("old_value", None)
                where_requested = params.get("where_column")
                where_operator = str(params.get("where_operator", "==")).strip()
                where_value = params.get("where_value", None)

                mask = pd.Series(True, index=updated_df.index)

                if where_requested:
                    where_col = _resolve_column_name(str(where_requested), list(updated_df.columns))
                    if not where_col:
                        result = (
                            f"Where-column '{where_requested}' not found. "
                            f"Available: {list(updated_df.columns)}"
                        )
                        updated_df.reset_index(drop=True, inplace=True)
                        return updated_df, result

                    where_series = updated_df[where_col]
                    typed_where_value = _coerce_value_for_series(where_series, where_value)
                    where_op_map = {
                        "==": where_series == typed_where_value,
                        "!=": where_series != typed_where_value,
                        ">": where_series > typed_where_value,
                        "<": where_series < typed_where_value,
                        ">=": where_series >= typed_where_value,
                        "<=": where_series <= typed_where_value,
                    }
                    if where_operator not in where_op_map:
                        result = f"Invalid where_operator '{where_operator}'."
                        updated_df.reset_index(drop=True, inplace=True)
                        return updated_df, result
                    mask = mask & where_op_map[where_operator]

                target_series = updated_df[target_col]
                if old_value is not None:
                    typed_old_value = _coerce_value_for_series(target_series, old_value)
                    mask = mask & (target_series == typed_old_value)

                typed_new_value = _coerce_value_for_series(target_series, new_value)
                affected = int(mask.sum())
                if affected == 0:
                    result = "No rows matched the update conditions."
                else:
                    updated_df.loc[mask, target_col] = typed_new_value
                    if old_value is not None:
                        result = (
                            f"Updated {affected} rows in '{target_col}': replaced '{old_value}' "
                            f"with '{typed_new_value}'."
                        )
                    elif where_requested:
                        result = (
                            f"Updated {affected} rows in '{target_col}' to '{typed_new_value}' "
                            f"where '{where_requested}' {where_operator} '{where_value}'."
                        )
                    else:
                        result = f"Updated {affected} rows in '{target_col}' to '{typed_new_value}'."

        else:
            result = f"Unknown operation: '{operation}'"

        updated_df.reset_index(drop=True, inplace=True)
        logger.info(f"Action result: {result}")
        return updated_df, result

    except Exception as exc:
        logger.error(f"Action execution failed: {exc}")
        return df, f"Action failed: {str(exc)}"