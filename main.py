import threading
import time
import os
import logging
from flask import Flask, request, redirect
from kiteconnect import KiteConnect

# --- CONFIGURATION ---
app = Flask(__name__)

# Get these from Railway Environment Variables later
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

# Global Variables
kite = KiteConnect(api_key=API_KEY)
access_token = None
bot_active = False

# --- TRADING BOT ENGINE (Runs in Background) ---
def start_trading_engine():
    global bot_active, access_token
    
    # 1. Setup Kite
    kite.set_access_token(access_token)
    print("🚀 Trading Engine Started!")
    
    # 2. The Infinite Loop
    while bot_active:
        try:
            # --- PLACE YOUR TRADING LOGIC HERE ---
            # example: smart_trader.check_market()
            # example: strategy_manager.monitor_risks()
            
            print("Running scheduled checks...")
            time.sleep(5) # Wait 5 seconds between checks
            
        except Exception as e:
            print(f"⚠️ Bot Error: {e}")
            time.sleep(5)

# --- WEB SERVER ROUTES ---

@app.route('/')
def home():
    """Shows the Status and Login Link"""
    if access_token:
        return "<h1>✅ Bot is Running</h1><p>Trading engine is active in the background.</p>"
    else:
        login_url = kite.login_url()
        return f'<h1>🔴 Bot Stopped</h1><a href="{login_url}"><h2>👉 Click here to Login to Zerodha</h2></a>'

@app.route('/callback')
def callback():
    """Handles the redirect from Zerodha"""
    global access_token, bot_active
    
    # 1. Get request_token from the URL
    request_token = request.args.get("request_token")
    
    if not request_token:
        return "Error: No token received."

    try:
        # 2. Generate Access Token
        data = kite.generate_session(request_token, api_secret=API_SECRET)
        access_token = data["access_token"]
        
        # 3. Start the Bot in a Background Thread
        if not bot_active:
            bot_active = True
            t = threading.Thread(target=start_trading_engine)
            t.daemon = True # Ensures thread dies if main app crashes
            t.start()
            
        return redirect('/')
        
    except Exception as e:
        return f"Login Failed: {e}"

# --- RUN SERVER ---
if __name__ == "__main__":
    # Railway provides a PORT variable, default to 5000 if not found
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
