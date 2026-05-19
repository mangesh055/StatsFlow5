import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.config import settings
from app.models.postgres_models import DataSession
import urllib.request
import urllib.error
import json

async def test_clean():
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        result = await session.execute(select(DataSession).order_by(DataSession.created_at.desc()))
        db_session = result.scalars().first()
        
        req = urllib.request.Request(
            f"http://localhost:8000/api/clean/{db_session.session_id}",
            data=json.dumps({"missing_strategy": "auto", "outlier_strategy": "auto"}).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        try:
            resp = urllib.request.urlopen(req)
            print("Success!")
        except urllib.error.HTTPError as e:
            print("HTTPError:", e.code, e.read().decode('utf-8'))

if __name__ == "__main__":
    asyncio.run(test_clean())
