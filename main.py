import os
import threading
import time
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
        .badge-otm { background-color: #6c757d; } /* Gray */
        .badge-itm { background-color: #198754; } /* Green */
        .badge-atm { background-color: #0d6efd; } /* Blue */
    </style>
</head>
<body class="bg-light">

<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h1>🚀 Pro Algo Dashboard <span class="badge bg-secondary">{{ status }}</span></h1>
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
        <div class="card-header bg-primary text-white d-flex justify-content-between align-items-center">
            <span class="fw-bold">⚡ Smart Execution Panel</span>
            <div>
                <span id="lot-size-badge" class="badge bg-warning text-dark me-2">Lot Size: -</span>
                <span id="live-ltp" class="badge bg-light text-dark">LTP: -</span>
            </div>
        </div>
        <div class="card-body">
            <form action="/trade" method="post" class="row g-3">
                
                <div class="col-md-3">
                    <label class="form-label fw-bold">1. Symbol</label>
                    <input type="text" id="symbol_search" name="index" class="form-control" placeholder="Search (e.g. NIFTY)" list="symbol_list" required autocomplete="off">
                    <datalist id="symbol_list"></datalist>
                </div>

                <div class="col-md-2">
                    <label class="form-label fw-bold">2. Expiry</label>
                    <select name="expiry" id="expiry_select" class="form-select" required>
                        <option value="" disabled selected>Select Symbol</option>
                    </select>
                </div>

                <div class="col-md-2">
                    <label class="form-label fw-bold">3. Type</label>
                    <select name="type" id="inst_type" class="form-select">
                        <option value="CE" selected>CALL (CE)</option>
                        <option value="PE">PUT (PE)</option>
                        <option value="FUT">FUTURE</option>
                    </select>
                </div>

                <div class="col-md-3">
                    <label class="form-label fw-bold">4. Strike Price</label>
                    <select name="strike" id="strike_select" class="form-select">
                        <option value="" disabled selected>Select Expiry</option>
                    </select>
                </div>

                <div class="col-md-2">
                    <label class="form-label fw-bold">Qty (Min: <span id="min-qty">0</span>)</label>
                    <input type="number" name="qty" id="qty_input" class="form-control" value="0">
                </div>

                <div class="col-md-8">
                     </div>
                <div class="col-md-2">
                     <select name="mode" class="form-select fw-bold">
                        <option value="PAPER">PAPER 📝</option>
                        <option value="LIVE">LIVE 🔴</option>
                    </select>
                </div>
                <div class="col-md-2 d-grid">
                    <button type="submit" class="btn btn-warning fw-bold">🚀 EXECUTE</button>
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
                            {% if trade.t1_hit %}<span class="badge bg-success">Safe</span>{% else %}{{ trade.status }}{% endif %}
                        </td>
                        <td>
                            {% if trade.mode == 'PAPER' and trade.status == 'OPEN' %}
                                <a href="/promote/{{ trade.id }}" class="btn btn-sm btn-outline-danger">Promote</a>
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
    let currentLTP = 0;
    let lotSize = 0;

    $(document).ready(function() {
        
        // 1. Symbol Search Autocomplete
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

        // 2. Fetch Details (Expiries, Lot Size) when Symbol Selected
        $('#symbol_search').on('change', function() {
            let symbol = $(this).val();
            if(!symbol) return;
            
            $('#live-ltp').text("Loading...");
            $('#expiry_select').html('<option>Loading...</option>');

            $.get('/api/details?symbol=' + symbol, function(data) {
                if(!data) { alert("Symbol not found"); return; }
                
                // Update Global Vars
                currentLTP = data.ltp;
                lotSize = data.lot_size;

                // Update UI
                $('#live-ltp').text("LTP: " + currentLTP);
                $('#lot-size-badge').text("Lot Size: " + lotSize);
                $('#min-qty').text(lotSize);
                $('#qty_input').val(lotSize); // Auto-fill Qty

                // Populate Expiry Dropdown
                let $expDropdown = $('#expiry_select');
                $expDropdown.empty();
                data.expiries.forEach(function(date, index) {
                    let label = date;
                    if(index === 0) label += " (Recent)";
                    $expDropdown.append(`<option value="${date}" ${index===0 ? 'selected' : ''}>${label}</option>`);
                });

                // Trigger Chain Update
                updateChain();
            });
        });

        // 3. Update Chain when Expiry or Type changes
        $('#expiry_select, #inst_type').on('change', function() {
            updateChain();
        });

        function updateChain() {
            let symbol = $('#symbol_search').val();
            let expiry = $('#expiry_select').val();
            let type = $('#inst_type').val();
            
            if(!symbol || !expiry) return;

            let $strikeDropdown = $('#strike_select');
            
            if (type === 'FUT') {
                $strikeDropdown.prop('disabled', true).html('<option value="FUT" selected>Future Contract</option>');
                return;
            }

            $strikeDropdown.prop('disabled', false).html('<option>Loading Chain...</option>');

            $.get(`/api/chain?symbol=${symbol}&expiry=${expiry}&type=${type}&ltp=${currentLTP}`, function(data) {
                $strikeDropdown.empty();
                
                if(data.length === 0) {
                     $strikeDropdown.html('<option>No Strikes Found</option>');
                     return;
                }

                data.forEach(function(item) {
                    let label = `${item.strike} (${item.label})`;
                    let isSelected = (item.label === "ATM") ? 'selected' : '';
                    $strikeDropdown.append(`<option value="${item.strike}" ${isSelected}>${label}</option>`);
                });
            });
        }
    });
</script>

</body>
</html>
"""

# --- ROUTES ---

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

# --- API ENDPOINTS (For JS) ---

@app.route('/api/search')
def api_search():
    query = request.args.get('q', '')
    results = smart_trader.search_symbols(query)
    return jsonify(results)

@app.route('/api/details')
def api_details():
    symbol = request.args.get('symbol', '')
    data = smart_trader.get_symbol_details(kite, symbol)
    return jsonify(data)

@app.route('/api/chain')
def api_chain():
    symbol = request.args.get('symbol')
    expiry = request.args.get('expiry')
    type_ = request.args.get('type')
    ltp = float(request.args.get('ltp', 0))
    
    data = smart_trader.get_chain_data(symbol, expiry, type_, ltp)
    return jsonify(data)

# --- EXECUTION ---

@app.route('/trade', methods=['POST'])
def place_trade():
    if not bot_active: return redirect('/')

    symbol_name = request.form['index']
    expiry = request.form['expiry']
    type_ = request.form['type']
    mode = request.form['mode']
    qty = int(request.form['qty'])
    
    final_symbol = ""
    strike = 0
    
    if type_ == 'FUT':
        # Construct Future Symbol
        final_symbol = smart_trader.get_exact_symbol(symbol_name, expiry, 0, "FUT")
    else:
        # Construct Option Symbol
        strike = float(request.form['strike'])
        final_symbol = smart_trader.get_exact_symbol(symbol_name, expiry, strike, type_)

    if not final_symbol:
        flash("❌ Error: Contract not found.")
        return redirect('/')

    result = strategy_manager.create_trade_direct(kite, mode, final_symbol, qty, sl_points=20)
    
    if result['status'] == 'success':
        flash(f"✅ Executed: {final_symbol}")
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
                smart_trader.fetch_instruments(kite)
        except Exception as e:
            flash(f"Login Error: {e}")
    return redirect('/')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
