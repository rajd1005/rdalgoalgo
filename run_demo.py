# run_demo.py
import sys
import os
import kiteconnect

# --- 1. Monkey Patch KiteConnect ---
# This forces the app to use our Mock Broker instead of the real one
from mock_broker import MockKiteConnect, MOCK_MARKET_DATA
kiteconnect.KiteConnect = MockKiteConnect

# --- 2. Import the main app ---
# We enable debug mode and disable reloader to prevent double-initialization issues
os.environ["FLASK_ENV"] = "development"
from main import app, kite, bot_active

# --- 3. Inject Demo Control Routes ---
from flask import request, jsonify, render_template

@app.route('/demo')
def demo_ui():
    return render_template('demo_panel.html')

@app.route('/mock-login-trigger')
def mock_login():
    # Simulate the Zerodha callback
    return '<script>window.location.href="/callback?request_token=mock_token_123&status=success";</script>'

@app.route('/demo/set_price', methods=['POST'])
def demo_set_price():
    # Update the global mock data
    sym = request.form.get('symbol')
    price = float(request.form.get('price'))
    MOCK_MARKET_DATA[sym] = price
    return jsonify({"status": "success", "message": f"Set {sym} to {price}"})

@app.route('/demo/get_state')
def demo_get_state():
    return jsonify(MOCK_MARKET_DATA)

# --- 4. Run the App ---
if __name__ == "__main__":
    print("\n" + "="*50)
    print("🚀 RUNNING IN DEMO SIMULATION MODE")
    print("1. Go to: http://127.0.0.1:5000")
    print("2. Click 'Login to Zerodha' (It will auto-login)")
    print("3. CONTROL PANEL: http://127.0.0.1:5000/demo")
    print("="*50 + "\n")
    
    # Using port 5000 or defined in config
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
