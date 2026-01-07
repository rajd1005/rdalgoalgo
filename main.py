import os
import threading
import time
import json
import logging
from flask import Flask, render_template_string, request, redirect, flash, jsonify
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

# --- TEMPLATE ---
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Pro Algo Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <style>
        .blink { animation: blinker 1.5s linear infinite; color: red; font-weight: bold; }
        @keyframes blinker { 50% { opacity: 0; } }
    </style>
</head>
<body class="bg-light">

<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h1>🚀 Pro Algo Dashboard <span class="badge bg-secondary" id="status-badge">{{ status }}</span></h1>
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

    <div class="card mb-4 shadow-sm border-primary">
        <div class="card-header bg-primary text-white d-flex justify-content-between">
            <span>⚡ Smart Execution Panel</span>
            <span id="live-ltp" class="badge bg-light text-dark">LTP: Waiting...</span>
        </div>
        <div class="card-body">
            <form action="/trade" method="post" class="row g-3">
                
                <div class="col-md-3">
                    <label class="form-label fw-bold">1. Search Symbol</label>
                    <input type="text" id="symbol_search" name="index" class="form-control" placeholder="e.g. NIFTY, RELIANCE" list="symbol_list" autocomplete="off" required>
                    <datalist id="symbol_list"></datalist>
                </div>

                <div class="col-md-2">
                    <label class="form-label fw-bold">2. Type</label>
                    <select name="type" id="inst_type" class="form-select">
                        <option value="CE" selected>CALL (CE)</option>
                        <option value="PE">PUT (PE)</option>
                        <option value="FUT">FUTURE</option>
                    </select>
                </div>

                <div class="col-md-3">
                    <label class="form-label fw-bold">3. Strike Price</label>
                    <select name="strike" id="strike_select" class="form-select">
                        <option value="" disabled selected>Select Symbol First</option>
                    </select>
                </div>

                <div class="col-md-2">
                    <label class="form-label">Qty</label>
                    <input type="number" name="qty" class="form-control" value="50">
                </div>
                
                <div class="col-md-2">
                    <label class="form-label">Mode</label>
                    <select name="mode" class="form-select fw-bold">
                        <option value="PAPER" class="text-primary">PAPER 📝</option>
                        <option value="LIVE" class="text-danger">LIVE 🔴</option>
                    </select>
                </div>

                <div class="col-12 d-grid mt-3">
                    <button type="submit" class="btn btn-warning btn-lg fw-bold">🚀 EXECUTE TRADE</button>
                </div>
            </form>
        </div>
    </div>

    <div class="card shadow-sm">
        <div class="card-header">📊 Active Positions</div>
        <div class="table-responsive">
            <table class="table table-hover mb-0 align-middle">
                <thead class="table-light">
                    <tr>
                        <th>Time</th>
                        <th>Symbol</th>
                        <th>Mode</th>
                        <th>Entry</th>
                        <th>LTP</th>
                        <th>Status</th>
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
                            {% if trade.t1_hit %}<span class="badge bg-success">Safe (T1 Hit)</span>{% else %}{{ trade.status }}{% endif %}
                        </td>
                        <td>
                            {% if trade.mode == 'PAPER' and trade.status == 'OPEN' %}
                                <a href="/promote/{{ trade.id }}" class="btn btn-sm btn-outline-danger">Promote 🚀</a>
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="7" class="text-center text-muted">No Active Trades</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>

<script>
    $(document).ready(function() {
        
        // A. Handle Symbol Search (Debounce)
        let timeout = null;
        $('#symbol_search').on('input', function() {
            clearTimeout(timeout);
            let keyword = $(this).val();
            if(keyword.length < 2) return;
            
            timeout = setTimeout(function() {
                $.get('/api/search?q=' + keyword, function(data) {
                    $('#symbol_list').empty();
                    data.forEach(function(item) {
                        $('#symbol_list').append('<option value="' + item + '">');
                    });
                });
            }, 300);
        });

        // B. Handle Symbol Selection -> Fetch Strikes
        $('#symbol_search').on('change', function() {
            let symbol = $(this).val();
            if(!symbol) return;

            $('#live-ltp').text("Fetching Data...");
            $('#strike_select').html('<option>Loading...</option>');

            $.get('/api/chain?symbol=' + symbol, function(data) {
                // 1. Update LTP Badge
                $('#live-ltp').text("LTP: " + data.ltp);

                // 2. Populate Dropdown
                let $dropdown = $('#strike_select');
                $dropdown.empty();
                
                let atm_strike = data.atm;
                
                data.strikes.forEach(function(strike) {
                    let isSelected = (strike == atm_strike) ? 'selected' : '';
                    let label = strike;
                    if (strike == atm_strike) label += " (ATM ✅)";
                    
                    $dropdown.append(`<option value="${strike}" ${isSelected}>${label}</option>`);
                });
            });
        });

        // C. Disable Strike Dropdown if FUT is selected
        $('#inst_type').on('change', function() {
            if($(this).val() == 'FUT') {
                $('#strike_select').prop('disabled', true).html('<option value="FUT">Future Contract</option>');
            } else {
                $('#strike_select').prop('disabled', false);
                $('#symbol_search').trigger('change'); // Refresh strikes
            }
        });
    });
</script>

</body>
</html>
"""

# --- FLASK ROUTES ---

@app.route('/')
def home():
    status_text = "ONLINE" if bot_active else "OFFLINE"
    trades = strategy_manager.load_trades()
    active_trades = [t for t in trades if t['status'] in ['OPEN', 'PROMOTED_LIVE']]
    return render_template_string(DASHBOARD_HTML, 
                                  status=status_text, 
                                  is_active=bot_active,
                                  login_url=kite.login_url(),
                                  trades=active_trades)

# --- API ROUTES (Used by JavaScript) ---

@app.route('/api/search')
def api_search():
    """Returns list of matching symbols"""
    query = request.args.get('q', '')
    results = smart_trader.search_symbols(query)
    return jsonify(results)

@app.route('/api/chain')
def api_chain():
    """Returns LTP and Strike List for a Symbol"""
    symbol = request.args.get('symbol', 'NIFTY')
    data = smart_trader.get_matrix_data(kite, symbol)
    return jsonify(data)

# --- TRADE EXECUTION ---

@app.route('/trade', methods=['POST'])
def place_trade():
    if not bot_active:
        flash("Please login first.")
        return redirect('/')

    symbol_name = request.form['index']
    type_ = request.form['type']
    mode = request.form['mode']
    qty = int(request.form['qty'])
    
    # Handling specific symbol finding logic
    final_symbol = ""
    
    if type_ == 'FUT':
        # Finding Future Symbol logic would go here
        # For now, let's assume current month future
        final_symbol = f"{symbol_name} FUT" # Simplified
    else:
        # Option Logic
        strike = float(request.form['strike'])
        # Find exact trading symbol from smart_trader
        final_symbol = smart_trader.get_exact_symbol(symbol_name, strike, type_)

    if not final_symbol:
        flash("❌ Error: Could not find exact trading symbol.")
        return redirect('/')

    # Execute via Strategy Manager
    # Note: We pass SL=20 hardcoded for now, or add input in form
    result = strategy_manager.create_trade_direct(kite, mode, final_symbol, qty, sl_points=20)
    
    if result['status'] == 'success':
        flash(f"✅ Trade Placed: {final_symbol}")
    else:
        flash(f"❌ Error: {result['message']}")
        
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
                smart_trader.fetch_instruments(kite) # Pre-load data
                
        except Exception as e:
            flash(f"Login Error: {e}")
    return redirect('/')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
