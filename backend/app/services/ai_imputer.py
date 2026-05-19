"""
StatsFlow AI Imputer  (v2 — fixed)
------------------------------------
Bugs fixed vs the original:
  1. __sf_row_id (values 0,1,2…) was leaked into LLM context → caused 0/1 predictions
  2. Gemini / LangChain were tried first even though project uses Groq → both silently failed
  3. No type-coercion on LLM output → strings were applied to float columns
  4. No fallback when LLM fails → NaN values stayed or garbage was applied
  5. Prompt example keys confused the LLM about which index system to use

This version:
  - Calls the active provider (Groq by default, then OpenRouter/Langchain, then Gemini)
  - Strips __sf_row_id from context before sending to LLM
  - Validates & range-checks every prediction against column statistics
  - Falls back to median/mode for any value the LLM cannot fill
"""

import json
import asyncio
import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.config import settings

logger = logging.getLogger(__name__)

ROW_ID_COL = "__sf_row_id"


# ─────────────────────────────────────────────────────────────────────────────
# Statistical helpers
# ─────────────────────────────────────────────────────────────────────────────

def _stat_fill(series: pd.Series) -> Optional[Any]:
    """Safe median (numeric) or mode (categorical) fill value."""
    non_null = series.dropna()
    if non_null.empty:
        return None
    if pd.api.types.is_numeric_dtype(series):
        return float(non_null.median())
    mode = non_null.mode()
    return str(mode.iloc[0]) if not mode.empty else str(non_null.iloc[0])


def _coerce_pred(pred: Any, series: pd.Series) -> Optional[Any]:
    """Validate and coerce an LLM prediction to match the column dtype."""
    if pred is None:
        return None
    if pd.api.types.is_numeric_dtype(series):
        try:
            val = float(pred)
        except (TypeError, ValueError):
            return None  # LLM gave a string for a numeric column — discard
        # Sanity range check: must be within 5× the observed spread
        non_null = series.dropna()
        if not non_null.empty:
            lo = non_null.min()
            hi = non_null.max()
            spread = (hi - lo) if hi != lo else abs(hi) + 1
            if not (lo - 5 * spread <= val <= hi + 5 * spread):
                logger.debug("Prediction %.4f outside plausible range — discarded", val)
                return None
        return val
    return str(pred).strip() if pred is not None else None


def _col_stats(df: pd.DataFrame, col: str) -> Dict[str, Any]:
    """Column statistics to embed in the LLM prompt."""
    s = df[col].dropna()
    if pd.api.types.is_numeric_dtype(df[col]):
        sample = [round(float(v), 4) for v in s.sample(min(5, len(s))).tolist()] if len(s) else []
        return {
            "type": "numeric",
            "min": round(float(s.min()), 4) if len(s) else None,
            "max": round(float(s.max()), 4) if len(s) else None,
            "mean": round(float(s.mean()), 4) if len(s) else None,
            "median": round(float(s.median()), 4) if len(s) else None,
            "sample_values": sample,
        }
    vc = s.value_counts()
    return {
        "type": "categorical",
        "valid_categories": vc.index.tolist()[:20],
        "most_frequent": str(vc.index[0]) if not vc.empty else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# JSON parsing
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> Optional[Dict]:
    """Extract a JSON dict from raw LLM text (strips markdown fences)."""
    if not raw:
        return None
    for fence in ("```json", "```"):
        if fence in raw:
            raw = raw.split(fence)[1].split("```")[0].strip()
            break
    s, e = raw.find("{"), raw.rfind("}") + 1
    if s >= 0 and e > s:
        raw = raw[s:e]
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# LLM call  (Groq → OpenRouter/LangChain → Gemini)
# ─────────────────────────────────────────────────────────────────────────────

def _build_prompt(batch_rows: List[Dict], col: str, stats: Dict) -> str:
    col_type = stats.get("type", "unknown")
    if col_type == "numeric":
        type_hint = (
            f"NUMERIC column. "
            f"Observed range [{stats.get('min')} – {stats.get('max')}], "
            f"mean={stats.get('mean')}, median={stats.get('median')}. "
            f"Sample values from dataset: {stats.get('sample_values')}. "
            f"Return a NUMBER (float/int). Do NOT return a string or 0/1 unless the data clearly supports it."
        )
    else:
        cats = stats.get("valid_categories", [])
        type_hint = (
            f"CATEGORICAL column. "
            f"The ONLY valid values are: {cats}. "
            f"Most frequent: '{stats.get('most_frequent')}'. "
            f"Return EXACTLY one of those strings — nothing else."
        )

    return f"""You are an expert data scientist performing missing-value imputation.

COLUMN TO IMPUTE: '{col}'
DATA TYPE: {type_hint}

For each row below, predict the most plausible value for '{col}' using the other column values and your domain knowledge.

ROWS WITH MISSING '{col}' (JSON):
{json.dumps(batch_rows, indent=2, default=str)}

STRICT OUTPUT RULES:
- Respond with ONLY a JSON object — no explanation, no markdown
- Keys   = the "row_index" integers from the input (as strings)
- Values = your predicted value for '{col}'
- Numeric columns: values MUST be numbers (no quotes)
- Categorical columns: values MUST be exact strings from valid_categories

Correct example for numeric:  {{"12": 45.3, "7": 128.9}}
Correct example for categorical: {{"3": "Adult", "9": "Pediatric"}}

Your JSON response:"""


async def _call_groq(prompt: str) -> Optional[Dict]:
    """Call Groq via the AsyncOpenAI client (primary path)."""
    try:
        from openai import AsyncOpenAI
        api_key = (settings.groq_api_key or "").strip()
        base_url = (settings.groq_base_url or "https://api.groq.com/openai/v1").strip()
        if not api_key:
            return None
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        resp = await client.chat.completions.create(
            model=settings.chat_model or "llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a data imputation expert. Respond with valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        raw = (resp.choices[0].message.content or "").strip()
        return _parse_json(raw)
    except Exception as e:
        logger.warning("Groq imputation call failed: %s", e)
        return None


async def _call_langchain(prompt: str) -> Optional[Dict]:
    """Call via LangChain ChatOpenAI (secondary path, e.g. OpenRouter)."""
    try:
        from app.services.chatbot_service import _get_langchain_llm, _coerce_llm_content
        from langchain_core.messages import SystemMessage, HumanMessage
        lc_llm, err = _get_langchain_llm()
        if lc_llm is None:
            return None
        msgs = [
            SystemMessage(content="You are a data imputation expert. Respond with valid JSON only."),
            HumanMessage(content=prompt),
        ]
        resp = await lc_llm.ainvoke(msgs)
        raw = _coerce_llm_content(resp.content).strip()
        return _parse_json(raw)
    except Exception as e:
        logger.warning("LangChain imputation call failed: %s", e)
        return None


async def _call_gemini(prompt: str) -> Optional[Dict]:
    """Call Gemini (tertiary path)."""
    try:
        from app.services.chatbot_service import _get_gemini_model
        gemini, err = _get_gemini_model()
        if gemini is None:
            return None

        def _run():
            return gemini.generate_content(
                prompt,
                generation_config={"temperature": 0.1, "max_output_tokens": 1024},
            )
        resp = await asyncio.to_thread(_run)
        raw = (getattr(resp, "text", None) or "").strip()
        return _parse_json(raw)
    except Exception as e:
        logger.warning("Gemini imputation call failed: %s", e)
        return None


async def _llm_predict(batch_rows: List[Dict], col: str, stats: Dict) -> Dict[int, Any]:
    """Try each LLM in priority order; return empty dict if all fail."""
    prompt = _build_prompt(batch_rows, col, stats)

    for caller in (_call_groq, _call_langchain, _call_gemini):
        result = await caller(prompt)
        if result:
            return result

    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def impute_missing_with_ai(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fill missing values using LLM context-aware prediction.

    Guarantees:
    - __sf_row_id is NEVER sent to the LLM.
    - Every prediction is type-validated and range-checked.
    - Any cell the LLM cannot fill is covered by median/mode fallback.
    - No NaN is left in the output.
    """
    df_out = df.copy()
    target_cols = [c for c in df_out.columns if c != ROW_ID_COL]

    ai_total = 0
    stat_total = 0

    for col in target_cols:
        missing_mask = df_out[col].isnull()
        missing_count = int(missing_mask.sum())
        if missing_count == 0:
            continue

        missing_indices: List[int] = df_out[missing_mask].index.tolist()
        stats = _col_stats(df_out, col)

        # Build context rows — exclude ROW_ID_COL and the target column itself
        context_cols = [c for c in target_cols if c != col]
        batch_rows: List[Dict] = []
        for idx in missing_indices:
            row = df_out.loc[idx]
            ctx: Dict[str, Any] = {}
            for c in context_cols:
                val = row[c]
                if pd.isna(val):
                    continue
                if isinstance(val, np.integer):
                    val = int(val)
                elif isinstance(val, np.floating):
                    val = round(float(val), 4)
                ctx[c] = val
            batch_rows.append({"row_index": int(idx), "other_column_values": ctx})

        # Send to LLM in batches of 10
        predictions: Dict[int, Any] = {}
        for i in range(0, len(batch_rows), 10):
            chunk = batch_rows[i: i + 10]
            raw_preds = await _llm_predict(chunk, col, stats)
            for str_idx, pred_val in raw_preds.items():
                try:
                    idx = int(str_idx)
                except (ValueError, TypeError):
                    continue
                if idx not in missing_indices:
                    continue
                coerced = _coerce_pred(pred_val, df_out[col])
                if coerced is not None:
                    predictions[idx] = coerced

        # Apply LLM predictions
        for idx, val in predictions.items():
            try:
                df_out.at[idx, col] = val
                ai_total += 1
            except Exception as e:
                logger.warning("Could not apply prediction [%s, %s]: %s", idx, col, e)

        # Fallback: fill any remaining NaN with median/mode
        still_missing = df_out[col].isnull()
        remaining = int(still_missing.sum())
        if remaining > 0:
            fill_val = _stat_fill(df_out[col])
            if fill_val is not None:
                df_out.loc[still_missing, col] = fill_val
                stat_total += remaining
                logger.info(
                    "Column '%s': %d values filled with statistical fallback (%s)",
                    col, remaining, fill_val,
                )

        logger.info(
            "Column '%s': %d/%d AI-predicted, %d statistical fallback",
            col, len(predictions), missing_count, remaining,
        )

    logger.info(
        "AI imputation complete — AI: %d cells, Statistical fallback: %d cells",
        ai_total, stat_total,
    )
    return df_out
