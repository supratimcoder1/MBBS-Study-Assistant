import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# Supabase
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_PUBLISHABLE_KEY: str = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
SUPABASE_SECRET_KEY: str = os.getenv("SUPABASE_SECRET_KEY", "")

# Database
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# Gemini
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# Supabase clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
