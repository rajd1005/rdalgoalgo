import os

# Zerodha Credentials
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

# Flask Settings
SECRET_KEY = "super_secret_algo_key"
PORT = int(os.environ.get("PORT", 5000))

# Trade Settings
DEFAULT_SL_POINTS = 20
