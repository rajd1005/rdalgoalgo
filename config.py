import os

# Zerodha Credentials (Set these in your Railway/Environment Variables)
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

# Flask Settings
SECRET_KEY = "super_secret_algo_key_v3"
PORT = int(os.environ.get("PORT", 5000))

# Trade Defaults
DEFAULT_SL_POINTS = 20

# Database Config
# Fix for Railway's postgres:// vs SQLAlchemy's postgresql://
uri = os.getenv("DATABASE_URL", "sqlite:///algo.db")
if uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

SQLALCHEMY_DATABASE_URI = uri
SQLALCHEMY_TRACK_MODIFICATIONS = False
