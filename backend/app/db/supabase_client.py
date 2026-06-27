"""Supabase client singleton.

Usage:
    from app.db.supabase_client import get_db
    db = get_db()
    db.table("users").select("*").execute()
"""

from functools import lru_cache

from supabase import Client, create_client

from app.config import SUPABASE_SERVICE_KEY, SUPABASE_URL


@lru_cache(maxsize=1)
def get_db() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be configured")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
