"""
StatsFlow AI Feature Engineering Service
-----------------------------------------
Analyzes the cleaned dataset using an LLM and generates meaningful
new features (ratios, interactions, transforms, binning, etc.).

Design principles:
- LLM receives full dataset context (schema, stats, sample rows, correlations)
- LLM returns structured JSON feature specs — no arbitrary code execution
- All operations are implemented via a whitelist of safe pandas/numpy ops
- Each feature includes a human-readable rationale
- Statistical fallback ensures no crashes if LLM output is partially invalid
"""

import json
import logging
import asyncio
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.config import settings

logger = logging.getLogger(__name__)

ROW_ID_COL = "__sf_row_id"

# ─────────────────────────────────────────────────────────────────────────────
# Safe operation registry
# Every feature the LLM can suggest must map to an entry here.
# ─────────────────────────────────────────────────────────────────────────────

def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.replace(0, np.nan)

SAFE_OPS: Dict[str, Any] = {
    # Two-column ops
    "ratio":       lambda df, c: _safe_div(df[c[0]], df[c[1]]),
    "difference":  lambda df, c: df[c[0]] - df[c[1]],
    "sum":         lambda df, c: df[c[0]] + df[c[1]],
    "product":     lambda df, c: df[c[0]] * df[c[1]],
    "percentage":  lambda df, c: _safe_div(df[c[0]], df[c[1]]) * 100,
    "interaction": lambda df, c: df[c[0]] * df[c[1]],
    # Single-column transforms
    "log1p":       lambda df, c: np.log1p(df[c[0]].clip(lower=0)),
    "sqrt":        lambda df, c: np.sqrt(df[c[0]].clip(lower=0)),
    "square":      lambda df, c: df[c[0]] ** 2,
    "abs":         lambda df, c: df[c[0]].abs(),
    "normalize":   lambda df, c: (df[c[0]] - df[c[0]].mean()) / (df[c[0]].std() + 1e-9),
    "inverse":     lambda df, c: 1.0 / (df[c[0]].replace(0, np.nan)),
    # Binning
    "bin3":        lambda df, c: pd.cut(df[c[0]], bins=3, labels=["low", "mid", "high"]).astype(str),
    "bin5":        lambda df, c: pd.cut(df[c[0]], bins=5, labels=["very_low","low","mid","high","very_high"]).astype(str),
}

EXPECTED_COLUMNS: Dict[str, int] = {
    "ratio": 2, "difference": 2, "sum": 2, "product": 2,
    "percentage": 2, "interaction": 2,
    "log1p": 1, "sqrt": 1, "square": 1, "abs": 1,
    "normalize": 1, "inverse": 1, "bin3": 1, "bin5": 1,
}


# ─────────────────────────────────────────────────────────────────────────────
# Dataset context builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_dataset_context(df: pd.DataFrame) -> Dict[str, Any]:
    """Build a compact but rich context dict to send to the LLM."""
    public_df = df.drop(columns=[ROW_ID_COL], errors="ignore")
    numeric_cols = public_df.select_dtypes(include=[np.number]).columns.tolist()
    cat_cols = [c for c in public_df.columns if c not in numeric_cols]

    col_info = []
    for col in public_df.columns:
        s = public_df[col].dropna()
        info: Dict[str, Any] = {
            "name": col,
            "type": "numeric" if col in numeric_cols else "categorical",
            "missing_pct": round(float(public_df[col].isnull().mean() * 100), 1),
        }
        if col in numeric_cols and len(s):
            info.update({
                "min": round(float(s.min()), 4),
                "max": round(float(s.max()), 4),
                "mean": round(float(s.mean()), 4),
                "std": round(float(s.std()), 4),
                "skew": round(float(s.skew()), 2),
            })
        elif len(s):
            vc = s.value_counts()
            info["top_values"] = vc.index.tolist()[:5]
            info["n_unique"] = int(s.nunique())
        col_info.append(info)

    # Correlation matrix (top pairs only)
    corr_pairs = []
    if len(numeric_cols) >= 2:
        corr = public_df[numeric_cols].corr().abs()
        for i, c1 in enumerate(numeric_cols):
            for c2 in numeric_cols[i+1:]:
                val = float(corr.loc[c1, c2])
                if not np.isnan(val):
                    corr_pairs.append({"col1": c1, "col2": c2, "corr": round(val, 3)})
        corr_pairs = sorted(corr_pairs, key=lambda x: x["corr"], reverse=True)[:10]

    # Sample rows (5 rows, all cols)
    sample = public_df.head(5).fillna("").to_dict(orient="records")
    for row in sample:
        for k, v in row.items():
            if isinstance(v, (np.integer,)):
                row[k] = int(v)
            elif isinstance(v, (np.floating,)):
                row[k] = round(float(v), 4)

    return {
        "shape": {"rows": int(public_df.shape[0]), "cols": int(public_df.shape[1])},
        "columns": col_info,
        "numeric_columns": numeric_cols,
        "categorical_columns": cat_cols,
        "top_correlations": corr_pairs,
        "sample_rows": sample,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Prompt builder
# ─────────────────────────────────────────────────────────────────────────────

_OP_DESCRIPTIONS = """
Available operations (use EXACTLY these operation names):
- ratio        : col1 / col2  (2 columns required)
- difference   : col1 - col2  (2 columns required)
- sum          : col1 + col2  (2 columns required)
- product      : col1 * col2  (2 columns required)
- percentage   : (col1 / col2) * 100  (2 columns required)
- interaction  : col1 * col2  (alias for product, use for cross-feature interactions)
- log1p        : log(1 + col1)  — good for right-skewed distributions (1 column)
- sqrt         : sqrt(col1)  — normalizes large ranges (1 column)
- square       : col1²  — amplifies differences (1 column)
- abs          : |col1|  — signed → unsigned (1 column)
- normalize    : (col1 - mean) / std  — z-score normalization (1 column)
- inverse      : 1 / col1  (1 column)
- bin3         : cut col1 into 3 equal bins: low/mid/high (1 column)
- bin5         : cut col1 into 5 equal bins (1 column)
"""

def _build_prompt(ctx: Dict) -> str:
    return f"""You are an expert data scientist performing feature engineering on a real-world dataset.

DATASET SUMMARY:
{json.dumps(ctx, indent=2)}

{_OP_DESCRIPTIONS}

TASK:
Suggest 5–8 meaningful new features that would genuinely improve predictive modeling or analytical value.
Use column names, correlations, and domain knowledge to propose features that make real-world sense.

RULES:
1. Only use column names listed in "columns" above — exact spelling
2. Only use operation names from the list above
3. For operations requiring 2 columns: columns must BOTH be numeric (unless noted)
4. For single-column ops: column must be numeric
5. bin3/bin5 can be applied to any numeric column
6. Avoid trivially redundant features (do not suggest ratio of a column with itself)
7. Prioritize features with real-world interpretation (NCR ratio, efficiency score, etc.)

RESPOND WITH ONLY a valid JSON array — no explanation, no markdown. Format:
[
  {{
    "name": "feature_name_snake_case",
    "description": "Plain English description of what this feature represents and why it is useful",
    "operation": "<one of the operation names above>",
    "columns": ["col_name_1"],
    "rationale": "Why this feature would help a model or analyst"
  }},
  ...
]

Your JSON:"""


# ─────────────────────────────────────────────────────────────────────────────
# LLM call
# ─────────────────────────────────────────────────────────────────────────────

def _parse_feature_json(raw: str) -> Optional[List[Dict]]:
    """Extract and parse a JSON array from LLM text."""
    if not raw:
        return None
    for fence in ("```json", "```"):
        if fence in raw:
            raw = raw.split(fence)[1].split("```")[0].strip()
            break
    s, e = raw.find("["), raw.rfind("]") + 1
    if s >= 0 and e > s:
        raw = raw[s:e]
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    return None


async def _call_groq(prompt: str) -> Optional[List[Dict]]:
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
                {"role": "system", "content": "You are a feature engineering expert. Respond with valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2048,
        )
        raw = (resp.choices[0].message.content or "").strip()
        return _parse_feature_json(raw)
    except Exception as e:
        logger.warning("Groq feature engineering call failed: %s", e)
        return None


async def _call_langchain(prompt: str) -> Optional[List[Dict]]:
    try:
        from app.services.chatbot_service import _get_langchain_llm, _coerce_llm_content
        from langchain_core.messages import SystemMessage, HumanMessage
        lc_llm, _ = _get_langchain_llm()
        if lc_llm is None:
            return None
        msgs = [
            SystemMessage(content="You are a feature engineering expert. Respond with valid JSON only."),
            HumanMessage(content=prompt),
        ]
        resp = await lc_llm.ainvoke(msgs)
        raw = _coerce_llm_content(resp.content).strip()
        return _parse_feature_json(raw)
    except Exception as e:
        logger.warning("LangChain feature engineering call failed: %s", e)
        return None


async def suggest_features(df: pd.DataFrame) -> List[Dict]:
    """
    Ask the LLM to suggest meaningful new features for the dataset.
    Returns a list of validated feature spec dicts.
    """
    ctx = _build_dataset_context(df)
    prompt = _build_prompt(ctx)

    raw_suggestions = None
    for caller in (_call_groq, _call_langchain):
        raw_suggestions = await caller(prompt)
        if raw_suggestions:
            break

    if not raw_suggestions:
        logger.warning("All LLM calls failed for feature engineering suggestions")
        return []

    public_df = df.drop(columns=[ROW_ID_COL], errors="ignore")
    numeric_cols = set(public_df.select_dtypes(include=[np.number]).columns.tolist())
    valid_cols = set(public_df.columns.tolist())

    validated: List[Dict] = []
    for spec in raw_suggestions:
        try:
            name = str(spec.get("name", "")).strip().replace(" ", "_")
            op = str(spec.get("operation", "")).strip().lower()
            cols = spec.get("columns", [])
            desc = str(spec.get("description", ""))
            rationale = str(spec.get("rationale", ""))

            if not name or not op or not cols:
                continue
            if op not in SAFE_OPS:
                logger.debug("Unknown operation '%s' — skipped", op)
                continue
            if not isinstance(cols, list) or len(cols) == 0:
                continue

            # Validate columns exist
            if not all(c in valid_cols for c in cols):
                missing = [c for c in cols if c not in valid_cols]
                logger.debug("Feature '%s' references unknown columns %s — skipped", name, missing)
                continue

            # Validate column count matches operation
            expected = EXPECTED_COLUMNS.get(op, 1)
            if len(cols) < expected:
                continue

            # Numeric check for ops that require it
            single_col_ops = {"log1p", "sqrt", "square", "abs", "normalize", "inverse", "bin3", "bin5"}
            two_col_ops = {"ratio", "difference", "sum", "product", "percentage", "interaction"}
            if op in single_col_ops and cols[0] not in numeric_cols:
                continue
            if op in two_col_ops and not all(c in numeric_cols for c in cols[:2]):
                continue

            # Compute a preview (first 5 values)
            try:
                preview_series = SAFE_OPS[op](public_df, cols)
                preview = []
                for v in preview_series.head(5).tolist():
                    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                        preview.append(None)
                    elif isinstance(v, (np.integer,)):
                        preview.append(int(v))
                    elif isinstance(v, (np.floating,)):
                        preview.append(round(float(v), 4))
                    else:
                        preview.append(v)
            except Exception as e:
                logger.debug("Preview failed for '%s': %s", name, e)
                preview = []

            validated.append({
                "name": name,
                "description": desc,
                "operation": op,
                "columns": cols[:expected],
                "rationale": rationale,
                "preview": preview,
            })

        except Exception as e:
            logger.debug("Feature spec validation error: %s", e)
            continue

    return validated


def apply_features(df: pd.DataFrame, selected: List[Dict]) -> Tuple[pd.DataFrame, List[Dict]]:
    """
    Apply the user-selected feature specs to the dataframe.
    Returns (updated_df, applied_log).
    """
    df_out = df.copy()
    public_df = df_out.drop(columns=[ROW_ID_COL], errors="ignore")
    applied_log = []

    for spec in selected:
        op = spec.get("operation", "")
        cols = spec.get("columns", [])
        name = spec.get("name", "")

        if not name or op not in SAFE_OPS:
            continue
        if not all(c in public_df.columns for c in cols):
            continue

        # Avoid overwriting existing columns — suffix if needed
        final_name = name
        if final_name in df_out.columns:
            final_name = f"{name}_feat"

        try:
            new_col = SAFE_OPS[op](public_df, cols)
            df_out[final_name] = new_col.values
            public_df[final_name] = new_col.values  # keep in sync for chaining

            # Sample values for the log
            sample = []
            for v in new_col.head(3).tolist():
                if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                    sample.append(None)
                elif isinstance(v, (np.integer,)):
                    sample.append(int(v))
                elif isinstance(v, (np.floating,)):
                    sample.append(round(float(v), 4))
                else:
                    sample.append(v)

            applied_log.append({
                "name": final_name,
                "operation": op,
                "columns": cols,
                "description": spec.get("description", ""),
                "sample_values": sample,
                "status": "applied",
            })
            logger.info("Feature '%s' applied via '%s' on %s", final_name, op, cols)

        except Exception as e:
            logger.warning("Failed to apply feature '%s': %s", name, e)
            applied_log.append({
                "name": name,
                "operation": op,
                "columns": cols,
                "description": spec.get("description", ""),
                "status": "failed",
                "error": str(e),
            })

    return df_out, applied_log
