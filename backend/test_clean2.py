import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.config import settings
from app.models.postgres_models import DataSession
from app.services.cleaning_engine import CleaningEngine
import pandas as pd

async def test_clean():
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        result = await session.execute(select(DataSession).order_by(DataSession.created_at.desc()))
        db_session = result.scalars().first()
        if not db_session:
            print("No session found.")
            return

        print(f"Testing session {db_session.session_id} - {db_session.filename}")
        
        raw_df = pd.read_csv(db_session.file_path, low_memory=False)
        # _load_raw_with_row_id logic
        raw_df["__sf_row_id"] = range(len(raw_df))
        
        try:
            # We skip AI impute because missing_strategy="auto"
            engine_clean = CleaningEngine(raw_df)
            cleaned_with_row_id, cleaning_report, operations = engine_clean.clean(
                missing_strategy="mean", # assume resolved
                outlier_strategy="iqr"   # assume resolved
            )
            print("Cleaned shape:", cleaned_with_row_id.shape)
            
            from app.services.health_score import compute_health_score
            cleaned_public_df = cleaned_with_row_id.drop(columns=["__sf_row_id"], errors="ignore")
            cleaned_health = compute_health_score(cleaned_public_df)
            
            from app.services.quality_scorecard import compute_quality_scorecard
            cleaned_quality = compute_quality_scorecard(cleaned_public_df)
            
            from app.services.anomaly_detection import detect_anomalies
            anomalies = detect_anomalies(cleaned_public_df)
            print("Done anomalies!")
            
        except Exception as e:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_clean())
