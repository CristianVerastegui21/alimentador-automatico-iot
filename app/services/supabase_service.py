import os
from functools import lru_cache
from supabase import create_client

@lru_cache(maxsize=1)
def obtener_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Faltan SUPABASE_URL / SUPABASE_KEY")
    return create_client(url, key)
