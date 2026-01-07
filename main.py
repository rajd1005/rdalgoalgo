import os
import time
import threading
import logging
from flask import Flask, request, redirect, render_template_string
from kiteconnect import KiteConnect
import smart_trader  # Import your custom logic module

# --- CONFIGURATION ---
app = Flask(__name__)

# Load keys from Railway Variables
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

# Global State Variables
kite = KiteConnect(api_key=API_KEY)
access_token = None
bot_active = False
latest_log = "Waiting for login..."

# Setup Logging to console (Railway Logs)
logging.basicConfig(level=logging.INFO)

# --- TRADING ENGINE (Runs in Background) ---
def start_trading_engine():
    global bot_active, access_token, latest_log
    
    # 1. Initialize Kite Session
    kite.set_access_token(access_token)
    logging.info("🚀 Trading Engine Started Successfully!")
    latest_log = "🚀 Engine Started. Downloading Instruments..."
    
    # 2. Setup: Download Instrument Master List (Once per session)
    try:
        smart_trader.fetch_instruments(kite)
        latest_log = "✅ Instruments Downloaded. Scanning Market..."
    except Exception as e:
        latest_log = f"❌ Setup Failed: {e}"
        logging.error(latest_log)
        return # Stop if setup fails

    # 3. The Infinite Loop
    while bot_active:
        try:
            # --- CORE TRADING LOGIC ---
            
            # Example: Find ATM Call Option for NIFTY
            # (In a real scenario, you'd check this every minute, not 10s)
            logging.info("🔎 Scanning for Opportunities...")
            
            # Simulate a market price (Replace with live LTP later)
            opportunity = smart_trader.find_option_symbol(kite, underlying="NIFTY", ltp=24200)
            
            if opportunity:
                msg = f"🎯 Found Trade: {opportunity['tradingsymbol']} (Strike: {opportunity['strike']})"
                print(msg)
                latest_log = msg
            else:
                latest_log = "⚠️ No matching contracts found."

            # Sleep to prevent high CPU usage (e.g., check every 10 seconds)
            time.sleep(10)

        except Exception as e:
            latest_log = f"⚠️ Loop Error: {e}"
            logging.error(latest_log)
            time.sleep(5) # Wait before retrying

# --- WEB SERVER ROUTES (The User Interface) ---

@app.route('/')
def home():
    """The Dashboard: Shows status and Login Button"""
    global access_token, bot_active, latest_log
    
    # Simple HTML Template
    html = """
    <div style="font-family: sans-serif; text-align: center; padding: 50px;">
        <h1>🤖 Zerodha Algo Bot</h1>
        <hr>
        <h3>Status: {{ status }}</h3>
        <p style="background: #f4f4f4; padding: 10px; border-radius: 5px;">📝 Log: {{ log }}</p>
        
        {% if not is_active %}
            <br>
            <a href="{{ login_url }}" style="background: #3498db; color: white; padding: 15px 30px; text-decoration: none; font-weight: bold; border-radius: 5px;">
                👉 Login to Zerodha
            </a>
        {% else %}
            <h2 style="color: green;">✅ Engine Running</h2>
        {% endif %}
    </div>
    """
    
    status_text = "🟢 ACTIVE" if bot_active else "🔴 STOPPED (Login Required)"
    
    return render_template_string(html, 
                                  status=status_text, 
                                  log=latest_log, 
                                  is_active=bot_active,
                                  login_url=kite.login_url())

@app.route('/callback')
def callback():
    """Handles the redirect from Zerodha after login"""
    global access_token, bot_active, latest_log
    
    request_token = request.args.get("request_token")
    
    if not request_token:
        return redirect('/')

    try:
        # 1. Exchange 'request_token' for 'access_token'
        data = kite.generate_session(request_token, api_secret=API_SECRET)
        access_token = data["access_token"]
        
        # 2. Start the background thread if not already running
        if not bot_active:
            bot_active = True
            t = threading.Thread(target=start_trading_engine)
            t.daemon = True # Ensures thread dies if app crashes
            t.start()
            
        return redirect('/')
        
    except Exception as e:
        latest_log = f"Login Failed: {e}"
        return redirect('/')

# --- START SERVER ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Threaded=True is important for Flask to handle the background loop + web requests
    app.run(host='0.0.0.0', port=port, threaded=True)
