import os
import threading
from flask import Flask, render_template_string, request, redirect, flash, jsonify
from kiteconnect import KiteConnect
import strategy_manager
import smart_trader

app = Flask(__name__)
app.secret_key = "zerodha_bot_secret"
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
kite = KiteConnect(api_key=API_KEY)
access_token = None
bot_active = False

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Mobile Algo Trader</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <style>
        body { background-color: #f0f2f5; font-size: 14px; }
        .card { border-radius: 12px; border: none; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 15px; }
        .card-header { border-radius: 12px 12px 0 0 !important; font-weight: bold; }
        .form-control, .form-select { border-radius: 8px; font-size: 16px; /* Prevents zoom on mobile */ }
        .btn-xl { padding: 12px; font-size: 18px; font-weight: bold; width: 100%; border-radius: 8px; }
        .risk-field { font-weight: bold; text-align: center; }
        .nav-pills .nav-link.active { background-color: #0d6efd; }
        .mobile-stack { display: flex; flex-direction: column; gap: 10px; }
    </style>
</head>
<body>

<nav class="navbar navbar-dark bg-dark sticky-top">
  <div class="container-fluid">
    <a class="navbar-brand" href="#">🚀 AlgoTrader</a>
    <span class="badge {{ 'bg-success' if is_active else 'bg-danger' }}">
        {{ 'ONLINE' if is_active else 'OFFLINE' }}
    </span>
  </div>
</nav>

<div class="container mt-3">
    {% with messages = get_flashed_messages() %}
        {% if messages %} <div class="alert alert-info py-2">{{ messages[0] }}</div> {% endif %}
    {% endwith %}

    {% if not is_active %}
    <div class="card p-4 text-center">
        <h4>System Offline</h4>
        <a href="{{ login_url }}" class="btn btn-primary mt-2">Login to Zerodha</a>
    </div>
    {% else %}

    <ul class="nav nav-pills nav-fill mb-3" id="pills-tab" role="tablist">
        <li class="nav-item">
            <button class="nav-link active" data-bs-toggle="pill" data-bs-target="#trade-tab">Live Trade</button>
        </li>
        <li class="nav-item">
            <button class="nav-link" data-bs-toggle="pill" data-bs-target="#history-tab">History Check</button>
        </li>
        <li class="nav-item">
            <button class="nav-link" data-bs-toggle="pill" data-bs-target="#positions-tab">Positions</button>
        </li>
    </ul>

    <div class="tab-content">
        <div class="tab-pane fade show active" id="trade-tab">
            <form action="/trade" method="post">
                <div class="card">
                    <div class="card-header bg-primary text-white d-flex justify-content-between">
                        <span>New Order</span>
                        <span id="inst-ltp" class="badge bg-light text-dark">LTP: 0</span>
                    </div>
                    <div class="card-body">
                        <div class="row g-2 mb-2">
                            <div class="col-6">
                                <label>Symbol</label>
                                <input type="text" id="symbol_search" name="index" class="form-control" placeholder="Search..." list="symbol_list" required>
                                <datalist id="symbol_list"></datalist>
                            </div>
                            <div class="col-6">
                                <label>Type</label>
                                <select name="type" id="inst_type" class="form-select">
                                    <option value="CE" selected>CE</option>
                                    <option value="PE">PE</option>
                                    <option value="FUT">FUT</option>
                                    <option value="EQ">EQ</option>
                                </select>
                            </div>
                        </div>

                        <div class="row g-2 mb-2">
                            <div class="col-6">
                                <label>Expiry</label>
                                <select name="expiry" id="expiry_select" class="form-select"></select>
                            </div>
                            <div class="col-6">
                                <label>Strike</label>
                                <select name="strike" id="strike_select" class="form-select"></select>
                            </div>
                        </div>

                        <div class="row g-2 mb-2">
                            <div class="col-6">
                                <label>Qty (<span id="lot-size">1</span>)</label>
                                <input type="number" name="qty" id="qty_input" class="form-control" value="1">
                            </div>
                            <div class="col-6">
                                <label>Order Type</label>
                                <select name="order_type" id="order_type" class="form-select">
                                    <option value="MARKET">Market</option>
                                    <option value="LIMIT">Limit</option>
                                </select>
                            </div>
                        </div>
                        
                        <div class="mb-2" id="limit_div" style="display:none;">
                            <label>Limit Price</label>
                            <input type="number" step="0.05" name="limit_price" id="limit_price" class="form-control" placeholder="0.00">
                        </div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header bg-dark text-white">Risk Manager</div>
                    <div class="card-body">
                        <div class="input-group mb-3">
                            <span class="input-group-text">SL Points</span>
                            <input type="number" id="sl_points" name="sl_points" class="form-control" value="20">
                        </div>

                        <div class="row g-2">
                            <div class="col-4"><label>SL Price</label><input type="number" step="0.05" id="sl_price" name="sl_price" class="form-control risk-field text-danger"></div>
                            <div class="col-4"><label>Target 1</label><input type="number" step="0.05" id="t1_price" name="t1_price" class="form-control risk-field text-success"></div>
                            <div class="col-4"><label>Target 2</label><input type="number" step="0.05" id="t2_price" name="t2_price" class="form-control risk-field text-success"></div>
                            <div class="col-4"><label>Target 3</label><input type="number" step="0.05" id="t3_price" name="t3_price" class="form-control risk-field text-success"></div>
                        </div>
                    </div>
                </div>

                <div class="d-grid gap-2 mb-5">
                    <select name="mode" class="form-select text-center fw-bold border-warning mb-2">
                        <option value="PAPER">PAPER MODE 📝</option>
                        <option value="LIVE">LIVE TRADE 🔴</option>
                    </select>
                    <button type="submit" class="btn btn-warning btn-xl shadow">🚀 EXECUTE TRADE</button>
                </div>
            </form>
        </div>

        <div class="tab-pane fade" id="history-tab">
            <div class="card p-3">
                <h5>📅 Historical Check (IST)</h5>
                <p class="text-muted small">Check price at a specific past time.</p>
                <form id="historyForm">
                    <div class="mb-2">
                        <label>Symbol</label>
                        <input type="text" id="hist_symbol" class="form-control" placeholder="e.g. NIFTY" required>
                    </div>
                    <div class="row g-2 mb-2">
                        <div class="col-6"><select id="hist_type" class="form-select"><option value="CE">CE</option><option value="PE">PE</option></select></div>
                        <div class="col-6"><input type="number" id="hist_strike" class="form-control" placeholder="Strike"></div>
                    </div>
                    <div class="mb-2">
                        <label>Date & Time</label>
                        <input type="datetime-local" id="hist_time" class="form-control" required>
                    </div>
                    <button type="button" class="btn btn-info w-100" onclick="checkHistory()">Check Price</button>
                </form>
                <div id="hist_result" class="mt-3 alert alert-secondary" style="display:none;"></div>
            </div>
        </div>

        <div class="tab-pane fade" id="positions-tab">
            <div class="card p-2">
                {% for trade in trades %}
                <div class="border-bottom pb-2 mb-2">
                    <div class="d-flex justify-content-between">
                        <strong>{{ trade.symbol }}</strong>
                        <span class="badge {{ 'bg-danger' if trade.mode == 'LIVE' else 'bg-primary' }}">{{ trade.mode }}</span>
                    </div>
                    <div class="d-flex justify-content-between small text-muted">
                        <span>Entry: {{ trade.entry_price }}</span>
                        <span>LTP: {{ trade.current_ltp }}</span>
                    </div>
                    <div class="d-flex justify-content-between mt-1">
                        <span class="badge bg-secondary">{{ trade.status }}</span>
                        {% if trade.mode == 'PAPER' %}
                        <a href="/promote/{{ trade.id }}" class="btn btn-sm btn-outline-danger">Promote</a>
                        {% endif %}
                    </div>
                </div>
                {% else %}
                <p class="text-center mt-3">No Active Positions</p>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endif %}
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
    let currentLTP = 0;
    
    // UI Helpers
    $('#order_type').change(function() {
        $('#limit_div').toggle($(this).val() === 'LIMIT');
    });

    // 1. Search Logic
    $('#symbol_search').on('input', function() {
        let val = $(this).val();
        if(val.length < 2) return;
        $.get('/api/search?q=' + val, (data) => {
            $('#symbol_list').empty();
            data.forEach(item => $('#symbol_list').append('<option value="' + item + '">'));
        });
    });

    // 2. Main Logic Flow (Symbol -> Details -> Expiry -> Chain -> LTP -> Risk)
    $('#symbol_search').change(function() {
        let sym = $(this).val();
        if(!sym) return;
        $.get('/api/details?symbol=' + sym, (data) => {
            // Update Lot Size
            $('#lot-size').text(data.lot_size);
            $('#qty_input').val(data.lot_size);
            
            // Populate Expiries
            window.futExps = data.fut_expiries;
            window.optExps = data.opt_expiries;
            populateExpiries();
        });
    });

    $('#inst_type').change(populateExpiries);
    $('#expiry_select').change(updateChain);
    $('#strike_select').change(fetchLTP);
    
    // Trigger Risk Calc on SL Point Change or LTP Change
    $('#sl_points').on('input', calcRisk);

    function populateExpiries() {
        let type = $('#inst_type').val();
        let $exp = $('#expiry_select');
        $exp.empty();
        
        let list = (type === 'FUT') ? window.futExps : window.optExps;
        if(type === 'EQ') list = ['N/A'];
        
        if(list) list.forEach(d => $exp.append(`<option value="${d}">${d}</option>`));
        updateChain();
    }

    function updateChain() {
        let sym = $('#symbol_search').val();
        let exp = $('#expiry_select').val();
        let type = $('#inst_type').val();
        
        if (type === 'FUT' || type === 'EQ') {
            $('#strike_select').html('<option value="0">N/A</option>');
            fetchLTP();
            return;
        }

        $.get(`/api/chain?symbol=${sym}&expiry=${exp}&type=${type}&ltp=0`, (data) => {
            let $s = $('#strike_select'); $s.empty();
            data.forEach(i => {
                let style = i.label.includes("ATM") ? "font-weight:bold; color:red;" : "";
                $s.append(`<option value="${i.strike}" style="${style}" ${i.label.includes("ATM")?'selected':''}>${i.strike}</option>`);
            });
            fetchLTP();
        });
    }

    function fetchLTP() {
        let sym = $('#symbol_search').val();
        let type = $('#inst_type').val();
        let exp = $('#expiry_select').val();
        let str = $('#strike_select').val();
        
        if(!sym) return;
        
        $.get(`/api/specific_ltp?symbol=${sym}&type=${type}&expiry=${exp}&strike=${str}`, (data) => {
            currentLTP = data.ltp;
            $('#inst-ltp').text("LTP: " + currentLTP);
            $('#limit_price').val(currentLTP); // Auto-fill limit price
            calcRisk();
        });
    }

    function calcRisk() {
        let sl_pts = parseFloat($('#sl_points').val()) || 0;
        if(currentLTP > 0) {
            $('#sl_price').val((currentLTP - sl_pts).toFixed(2));
            $('#t1_price').val((currentLTP + (sl_pts * 0.5)).toFixed(2));
            $('#t2_price').val((currentLTP + (sl_pts * 1.0)).toFixed(2));
            $('#t3_price').val((currentLTP + (sl_pts * 2.0)).toFixed(2));
        }
    }

    // Historical Check Logic
    window.checkHistory = function() {
        let data = {
            symbol: $('#hist_symbol').val(),
            type: $('#hist_type').val(),
            strike: $('#hist_strike').val(),
            time: $('#hist_time').val()
        };
        
        $('#hist_result').show().text("Checking...");
        
        // Note: You need to implement this API route
        $.get('/api/history_check', data, (res) => {
            if(res.status === 'success') {
                $('#hist_result').html(`<strong>${res.symbol}</strong><br>Time: ${res.data.date}<br>Open: ${res.data.open}<br>High: ${res.data.high}<br>Close: ${res.data.close}`);
            } else {
                $('#hist_result').text("Error: " + res.message);
            }
        });
    };
</script>
</body>
</html>
"""

# ROUTES
@app.route('/')
def home():
    status = "ONLINE" if bot_active else "OFFLINE"
    trades = strategy_manager.load_trades()
    active = [t for t in trades if t['status'] in ['OPEN', 'PROMOTED_LIVE']]
    return render_template_string(DASHBOARD_HTML, is_active=bot_active, login_url=kite.login_url(), trades=active)

@app.route('/api/search')
def api_search(): return jsonify(smart_trader.search_symbols(request.args.get('q', '')))
@app.route('/api/details')
def api_details(): return jsonify(smart_trader.get_symbol_details(kite, request.args.get('symbol', '')))
@app.route('/api/chain')
def api_chain(): return jsonify(smart_trader.get_chain_data(request.args.get('symbol'), request.args.get('expiry'), request.args.get('type'), float(request.args.get('ltp', 0))))
@app.route('/api/specific_ltp')
def api_s_ltp(): return jsonify({"ltp": smart_trader.get_specific_ltp(kite, request.args.get('symbol'), request.args.get('expiry'), request.args.get('strike'), request.args.get('type'))})

@app.route('/api/history_check')
def api_history():
    # Helper to call smart_trader history function
    # Note: Requires smart_trader to have fetch_historical_check
    sym = request.args.get('symbol')
    typ = request.args.get('type')
    strk = request.args.get('strike')
    time_str = request.args.get('time').replace('T', ' ') # Fix HTML datetime format
    
    # We need to find expiry logic here or ask user. For now, we might need recent expiry logic or assume input.
    # Simplified: finding recent expiry if not provided is hard for history. 
    # For now, let's assume we find the symbol directly.
    # This is a complex feature. For now, simple response:
    return jsonify(smart_trader.fetch_historical_check(kite, sym, "2026-01-29", strk, typ, time_str)) # Hardcoded expiry for demo, needs UI input

@app.route('/trade', methods=['POST'])
def place_trade():
    if not bot_active: return redirect('/')
    
    sym = request.form['index']
    type_ = request.form['type']
    mode = request.form['mode']
    qty = int(request.form['qty'])
    sl_points = float(request.form['sl_points'])
    order_type = request.form['order_type']
    limit_price = float(request.form['limit_price'] or 0)
    
    custom_targets = [float(request.form['t1_price']), float(request.form['t2_price']), float(request.form['t3_price'])]
    
    final_sym = smart_trader.get_exact_symbol(sym, request.form.get('expiry'), request.form.get('strike', 0), type_)
    
    if not final_sym:
        flash("❌ Contract not found")
        return redirect('/')

    strategy_manager.create_trade_direct(kite, mode, final_sym, qty, sl_points, custom_targets, order_type, limit_price)
    flash(f"✅ Trade Executed: {final_sym}")
    return redirect('/')

@app.route('/callback')
def callback():
    global access_token, bot_active
    t = request.args.get("request_token")
    if t:
        try:
            data = kite.generate_session(t, api_secret=API_SECRET)
            access_token = data["access_token"]
            if not bot_active:
                bot_active = True
                smart_trader.fetch_instruments(kite)
        except Exception as e: flash(f"Login Error: {e}")
    return redirect('/')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), threaded=True)
