import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.config import settings
from app.models.postgres_models import DataSession
from app.services.cleaning_engine import CleaningEngine
import pandas as pd
from app.routers.cleaning import (
    _build_change_bundle,
    _build_review_state_response,
    _build_feed_baseline_partner_profile,
    generate_pipeline_script,
    _public_df
)
import json

async def test_clean():
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        result = await session.execute(select(DataSession).order_by(DataSession.created_at.desc()))
        db_session = result.scalars().first()

        print(f"Testing session {db_session.session_id}")
        
        raw_df = pd.read_csv(db_session.file_path, low_memory=False)
        raw_df["__sf_row_id"] = range(len(raw_df))
        
        engine_clean = CleaningEngine(raw_df)
        cleaned_with_row_id, cleaning_report, operations = engine_clean.clean(
            missing_strategy="mean",
            outlier_strategy="iqr"
        )
        
        try:
            print("Building baseline...")
            baseline_partner_profile = await _build_feed_baseline_partner_profile(db=session, current_session=db_session)
            print("Baseline ok")
            
            print("Generating pipeline script...")
            pipeline_script = generate_pipeline_script(
                filename=db_session.filename,
                operations=operations,
                missing_strategy="mean",
                outlier_strategy="iqr",
            )
            print("Script generated ok")
            
            print("Building response...")
            response_dict = _build_review_state_response(
                session=db_session,
                raw_with_row_id=raw_df,
                cleaned_with_row_id=cleaned_with_row_id
            )
            print("Serializing...")
            import math
            import numpy as np
            def default_encoder(obj):
                if isinstance(obj, (np.integer, np.int64)): return int(obj)
                if isinstance(obj, (np.floating, np.float64)):
                    if math.isnan(obj) or math.isinf(obj): return None
                    return float(obj)
                if isinstance(obj, np.ndarray): return obj.tolist()
                raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")
                
            json.dumps(response_dict, default=default_encoder)
            print("All good!")
        except Exception as e:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_clean())
