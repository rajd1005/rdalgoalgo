import os
import threading
import time
import logging
from flask import Flask, render_template_string, request, redirect, flash
from kiteconnect import KiteConnect
import strategy_manager
import smart_trader

# --- CONFIGURATION ---
app = Flask(__name__)
app.secret_key = "zerodha_bot_secret"

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

kite = KiteConnect(api_key=API_KEY)
access_token = None
bot_active = False

# --- TEMPLATE (The HTML Dashboard) ---
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Algo Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <meta http-equiv="refresh" content="10"> </head>
<body class="bg-light">

<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h1>🚀 Algo Dashboard <span class="badge bg-secondary">{{ status }}</span></h1>
        {% if not is_active %}
            <a href="{{ login_url }}" class="btn btn-primary">Login to Zerodha</a>
        {% else %}
            <button class="btn btn-success" disabled>System Online</button>
        {% endif %}
    </div>

    {% with messages = get_flashed_messages() %}
        {% if messages %}
            <div class="alert alert-info">{{ messages[0] }}</div>
        {% endif %}
    {% endwith %}

    <div class="card mb-4 shadow-sm">
        <div class="card-header bg-dark text-white">⚡ Instant Execution</div>
        <div class="card-body">
            <form action="/trade" method="post" class="row g-3">
                <div class="col-md-2">
                    <label>Index</label>
                    <select name="index" class="form-select">
                        <option value="NIFTY 50">NIFTY</option>
                        <option value="NIFTY BANK">BANKNIFTY</option>
                    </select>
                </div>
                <div class="col-md-2">
                    <label>Type</label>
                    <select name="type" class="form-select">
                        <option value="CE">CALL (CE)</option>
                        <option value="PE">PUT (PE)</option>
                    </select>
                </div>
                <div class="col-md-2">
                    <label>Mode</label>
                    <select name="mode" class="form-select">
                        <option value="PAPER">PAPER 📝</option>
                        <option value="LIVE">LIVE 🔴</option>
                    </select>
                </div>
                <div class="col-md-2">
                    <label>Qty</label>
                    <input type="number" name="qty" class="form-control" value="50">
                </div>
                <div class="col-md-2">
                    <label>SL (Pts)</label>
                    <input type="number" name="sl" class="form-control" value="20">
                </div>
                <div class="col-md-2 d-grid">
                    <label>&nbsp;</label>
                    <button type="submit" class="btn btn-warning fw-bold">EXECUTE</button>
                </div>
            </form>
        </div>
    </div>

    <div class="card shadow-sm">
        <div class="card-header">📊 Active Positions</div>
        <div class="table-responsive">
            <table class="table table-hover mb-0">
                <thead class="table-light">
                    <tr>
                        <th>Time</th>
                        <th>Symbol</th>
                        <th>Mode</th>
                        <th>Entry</th>
                        <th>LTP</th>
                        <th>T1 Status</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {% for trade in trades %}
                    <tr class="{% if trade.mode == 'LIVE' %}table-danger{% else %}table-info{% endif %}">
                        <td>{{ trade.id }}</td>
                        <td><strong>{{ trade.symbol }}</strong></td>
                        <td>{{ trade.mode }}</td>
                        <td>{{ trade.entry_price }}</td>
                        <td>{{ trade.current_ltp }}</td>
                        <td>
                            {% if trade.t1_hit %}
                                <span class="badge bg-success">SECURED (SL @ Cost)</span>
                            {% else %}
                                <span class="badge bg-secondary">Pending</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if trade.mode == 'PAPER' and trade.status == 'OPEN' %}
                                <a href="/promote/{{ trade.id }}" class="btn btn-sm btn-outline-danger">Promote to Live 🚀</a>
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="7" class="text-center">No Active Trades</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>

</body>
</html>
"""

# --- ROUTES ---

@app.route('/')
def home():
    status_text = "ONLINE" if bot_active else "OFFLINE"
    trades = strategy_manager.load_trades()
    # Filter only OPEN trades for the dashboard
    active_trades = [t for t in trades if t['status'] in ['OPEN', 'PROMOTED_LIVE']]
    
    return render_template_string(DASHBOARD_HTML, 
                                  status=status_text, 
                                  is_active=bot_active,
                                  login_url=kite.login_url(),
                                  trades=active_trades)

@app.route('/trade', methods=['POST'])
def place_trade():
    if not bot_active:
        flash("System Offline. Please Login first.")
        return redirect('/')
        
    idx = request.form['index']
    typ = request.form['type']
    mode = request.form['mode']
    qty = int(request.form['qty'])
    sl = int(request.form['sl'])
    
    result = strategy_manager.create_trade(kite, mode, idx, typ, qty, sl)
    
    if result['status'] == 'success':
        flash(f"Trade Executed: {result['trade']['symbol']}")
    else:
        flash(f"Error: {result['message']}")
        
    return redirect('/')

@app.route('/promote/<trade_id>')
def promote(trade_id):
    if not bot_active:
        return redirect('/')
        
    success = strategy_manager.promote_to_live(kite, trade_id)
    if success:
        flash("Trade Promoted to LIVE Execution!")
    else:
        flash("Promotion Failed.")
    return redirect('/')

@app.route('/callback')
def callback():
    global access_token, bot_active
    request_token = request.args.get("request_token")
    if request_token:
        try:
            data = kite.generate_session(request_token, api_secret=API_SECRET)
            access_token = data["access_token"]
            
            if not bot_active:
                bot_active = True
                t = threading.Thread(target=background_loop)
                t.daemon = True
                t.start()
                
            # Perform initial instrument download
            smart_trader.fetch_instruments(kite)
            
        except Exception as e:
            flash(f"Login Error: {e}")
            
    return redirect('/')

# --- BACKGROUND THREAD ---
def background_loop():
    global bot_active, access_token
    kite.set_access_token(access_token)
    
    while bot_active:
        try:
            strategy_manager.update_risk_engine(kite)
            time.sleep(2) # Check every 2 seconds
        except Exception as e:
            print(f"Loop Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
