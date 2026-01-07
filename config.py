import os

# Zerodha Credentials (Set these in Railway Variables)
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

# Flask Settings
SECRET_KEY = "super_secret_algo_key_v2"
PORT = int(os.environ.get("PORT", 5000))

# Default Settings
DEFAULT_SL_POINTS = 20
