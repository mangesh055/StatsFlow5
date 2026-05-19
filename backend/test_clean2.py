import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.config import settings
from app.models.postgres_models import DataSession
from app.services.cleaning_engine import CleaningEngine
import pandas as pd
from app.routers.cleaning import _build_change_bundle

async def test_clean():
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        result = await session.execute(select(DataSession).order_by(DataSession.created_at.desc()))
        db_session = result.scalars().first()

        print(f"Testing session {db_session.session_id}")
        
        raw_df = pd.read_csv(db_session.file_path, low_memory=False)
        raw_df["__sf_row_id"] = range(len(raw_df))
        
        try:
            engine_clean = CleaningEngine(raw_df)
            cleaned_with_row_id, cleaning_report, operations = engine_clean.clean(
                missing_strategy="mean",
                outlier_strategy="iqr"
            )
            
            bundle = _build_change_bundle(
                raw_with_row_id=raw_df,
                cleaned_with_row_id=cleaned_with_row_id,
                cleaning_report=cleaning_report,
            )
            print("Done change bundle!", len(bundle))
            
            from app.routers.cleaning import _build_review_state_response
            response = _build_review_state_response(
                session=db_session,
                raw_with_row_id=raw_df,
                cleaned_with_row_id=cleaned_with_row_id
            )
            print("Done review response!")
        except Exception as e:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_clean())
