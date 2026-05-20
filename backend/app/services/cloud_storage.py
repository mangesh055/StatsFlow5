"""
Supabase Storage Service
------------------------
Handles uploading and downloading files to/from Supabase Storage.
"""

import os
import logging
from supabase import create_client, Client
from app.config import settings

logger = logging.getLogger(__name__)

supabase: Client | None = None

if settings.supabase_url and settings.supabase_key:
    try:
        supabase = create_client(settings.supabase_url, settings.supabase_key)
        logger.info(f"✅ Supabase Storage initialized -> {settings.supabase_bucket}")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase: {e}")
else:
    logger.warning("Supabase URL or Key not set. Cloud storage is disabled.")

def get_cloud_object_name(session_id: str, suffix: str = "raw") -> str:
    """Generates a consistent object key for Supabase."""
    return f"{suffix}/{session_id}_{suffix}.csv"

def sync_to_cloud(local_path: str):
    """Automatically parses filename and uploads to the correct Supabase folder."""
    if not supabase:
        return
    
    if not os.path.exists(local_path):
        logger.error(f"Cannot sync: file {local_path} does not exist.")
        return

    basename = os.path.basename(local_path)
    # Parse object name based on suffix
    if basename.endswith("_raw.csv"):
        object_name = f"raw/{basename}"
    elif basename.endswith("_cleaned.csv"):
        object_name = f"cleaned/{basename}"
    elif basename.endswith("_chatbot_working.csv") or basename.endswith("_working.csv"):
        object_name = f"working/{basename}"
    else:
        object_name = f"other/{basename}"

    try:
        with open(local_path, "rb") as f:
            # Overwrite if exists
            supabase.storage.from_(settings.supabase_bucket).upload(
                path=object_name, 
                file=f,
                file_options={"upsert": "true"}
            )
        logger.info(f"✅ Synced to cloud: {object_name}")
    except Exception as e:
        logger.error(f"❌ Cloud sync failed for {basename}: {e}")

def ensure_local_copy(object_name: str, local_path: str):
    """Downloads the file from Supabase if it doesn't exist locally."""
    if os.path.exists(local_path) or not supabase:
        return

    try:
        res = supabase.storage.from_(settings.supabase_bucket).download(object_name)
        with open(local_path, "wb") as f:
            f.write(res)
        logger.info(f"⬇️ Downloaded from cloud: {object_name}")
    except Exception as e:
        logger.error(f"❌ Failed to download {object_name}: {e}")
