import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ALIBABA_ACCESS_KEY_ID = os.getenv("ALIBABA_ACCESS_KEY_ID", "")
ALIBABA_ACCESS_KEY_SECRET = os.getenv("ALIBABA_ACCESS_KEY_SECRET", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "changeme")
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
ASR_CONFIDENCE_THRESHOLD = int(os.getenv("ASR_CONFIDENCE_THRESHOLD", "80"))
PLAYBOOK_MIN_RECORDINGS = int(os.getenv("PLAYBOOK_MIN_RECORDINGS", "5"))

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma"}
MAX_FILE_SIZE_MB = 200
PROCESSING_TIMEOUT_MINUTES = 10
