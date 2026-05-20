import asyncio
import subprocess
import urllib.request
import urllib.error
import json
import time

async def run_test():
    print("Starting uvicorn on port 8001...")
    proc = subprocess.Popen(
        ["python", "-m", "uvicorn", "main:app", "--port", "8001"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    time.sleep(5) # wait for server to start
    
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.postgres_models import DataSession
    
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        result = await session.execute(select(DataSession).order_by(DataSession.created_at.desc()))
        db_session = result.scalars().first()
        
    req = urllib.request.Request(
        f"http://localhost:8001/api/clean/{db_session.session_id}",
        data=json.dumps({"missing_strategy": "auto", "outlier_strategy": "auto"}).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        print("Making request...")
        urllib.request.urlopen(req)
        print("Request succeeded!")
    except Exception as e:
        print("Request failed:", str(e))
        
    proc.terminate()
    print("Server output:")
    try:
        out, _ = proc.communicate(timeout=60)
    except Exception:
        proc.kill()
        out, _ = proc.communicate()
    
    # only print the traceback
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if "ERROR:" in line or "Traceback" in line:
            print("\n".join(lines[i:]))
            break
            
if __name__ == "__main__":
    asyncio.run(run_test())
