import pandas as pd
import numpy as np
import json
import asyncio
import logging
from typing import Dict, Any, List
from app.services.chatbot_service import _get_gemini_model, _get_langchain_llm, _parse_llm_response, _coerce_llm_content

logger = logging.getLogger(__name__)

async def predict_missing_batch(df: pd.DataFrame, missing_col: str, missing_indices: List[int]) -> Dict[int, Any]:
    """Predict a batch of missing values using the active LLM."""
    # Build batch prompt
    batch_data = []
    for idx in missing_indices:
        row_dict = df.loc[idx].drop(missing_col, errors='ignore').to_dict()
        # Clean up NaNs
        clean_row = {k: v for k, v in row_dict.items() if not pd.isna(v)}
        batch_data.append({"index": idx, "context": clean_row})
    
    prompt = f"""You are an advanced AI data imputer. Your task is to accurately predict the missing value for the column '{missing_col}'.
Use the context from the other columns in each row to infer the most logical, meaningful, and correct missing value.
Draw upon your general knowledge and pattern recognition capabilities to fill in the missing data correctly.

Here is the data in JSON format:
{json.dumps(batch_data, indent=2, default=str)}

Respond ONLY with a valid JSON dictionary mapping the integer "index" to the predicted value.
Example format:
{{
  "0": "predicted_value_1",
  "5": "predicted_value_2"
}}
"""

    # Try Gemini first
    gemini, _ = _get_gemini_model()
    if gemini:
        try:
            def _run_gen():
                return gemini.generate_content(prompt, generation_config={"temperature": 0.1})
            resp = await asyncio.to_thread(_run_gen)
            raw = (getattr(resp, "text", None) or "").strip()
            # extract JSON block
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            return json.loads(raw)
        except Exception as e:
            logger.error(f"Gemini AI Imputation failed: {e}")

    # Fallback to Langchain
    lc_llm, _ = _get_langchain_llm()
    if lc_llm:
        try:
            from langchain_core.messages import SystemMessage, HumanMessage
            msgs = [SystemMessage(content="You are a strict data imputation AI that only outputs valid JSON."), HumanMessage(content=prompt)]
            resp = await lc_llm.ainvoke(msgs)
            raw = _coerce_llm_content(resp.content).strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            return json.loads(raw)
        except Exception as e:
            logger.error(f"Langchain AI Imputation failed: {e}")

    return {}


async def impute_missing_with_ai(df: pd.DataFrame) -> pd.DataFrame:
    """Impute missing values using AI/LLM context-aware filling."""
    df_out = df.copy()
    
    # Process column by column
    for col in df_out.columns:
        if col == "__sf_row_id":
            continue
            
        missing_mask = df_out[col].isnull()
        missing_count = missing_mask.sum()
        
        if missing_count == 0:
            continue
            
        # We only impute if there are <= 50 missing values per column to avoid massive API costs/delays
        if missing_count > 100:
            logger.warning(f"Too many missing values in {col} ({missing_count}) for AI imputation. Skipping this column.")
            continue
            
        missing_indices = df_out[missing_mask].index.tolist()
        
        # Batch sizes of 10
        batch_size = 10
        for i in range(0, len(missing_indices), batch_size):
            batch = missing_indices[i:i+batch_size]
            predictions = await predict_missing_batch(df_out, col, batch)
            
            # Apply predictions
            for str_idx, pred_val in predictions.items():
                try:
                    idx = int(str_idx)
                    if idx in batch:
                        df_out.at[idx, col] = pred_val
                except Exception as e:
                    logger.error(f"Error applying AI prediction for idx {str_idx}: {e}")
                    
    return df_out
