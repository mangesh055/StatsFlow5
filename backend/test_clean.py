import asyncio
import pandas as pd
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.config import settings
from app.models.postgres_models import DataSession
from app.services.cleaning_engine import CleaningEngine
from app.services.ai_imputer import impute_missing_with_ai

async def test_clean():
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # get the latest session
        result = await session.execute(select(DataSession).order_by(DataSession.created_at.desc()))
        db_session = result.scalars().first()
        if not db_session:
            print("No session found.")
            return

        print(f"Testing session {db_session.session_id}")
        raw_df = pd.read_csv(db_session.file_path, low_memory=False)
        raw_df['__sf_row_id'] = range(len(raw_df))
        
        try:
            print("Running ai imputer...")
            ai_imputed_df = await impute_missing_with_ai(raw_df)
            print("Running cleaning engine...")
            engine = CleaningEngine(ai_imputed_df)
            cleaned_df, report, ops = engine.clean()
            print("Done cleaning!")
            
            from app.services.quality_scorecard import compute_quality_scorecard
            print("Running quality scorecard...")
            quality = compute_quality_scorecard(cleaned_df)
            print("Done quality scorecard!")
        except Exception as e:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_clean())
