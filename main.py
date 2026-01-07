import os
import threading
import time
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

# --- TEMPLATE ---
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Master Algo Terminal</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <style>
        .badge-ltp { font-size: 0.9rem; background: #343a40; color: #fff; }
        .atm-option { color: red; font-weight: bold; }
        .input-group-text { cursor: pointer; user-select: none; }
    </style>
</head>
<body class="bg-light">

<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h1>🚀 Master Terminal <span class="badge bg-secondary">{{ status }}</span></h1>
        {% if not is_active %}
            <a href="{{ login_url }}" class="btn btn-primary">Login to Zerodha</a>
        {% else %}
            <button class="btn btn-success" disabled>System Online</button>
        {% endif %}
    </div>

    {% with messages = get_flashed_messages() %}
        {% if messages %} <div class="alert alert-info">{{ messages[0] }}</div> {% endif %}
    {% endwith %}

    <div class="card mb-4 shadow-sm border-dark">
        <div class="card-header bg-dark text-white d-flex justify-content-between align-items-center">
            <span class="fw-bold">⚡ Trade Control</span>
            <div>
                <span id="underlying-ltp" class="badge bg-secondary me-2">Spot: -</span>
                <span id="instrument-ltp" class="badge bg-warning text-dark">Inst. LTP: -</span>
            </div>
        </div>
        <div class="card-body">
            <form action="/trade" method="post" class="row g-3">
                
                <div class="col-md-3">
                    <label class="form-label fw-bold">1. Symbol</label>
                    <input type="text" id="symbol_search" name="index" class="form-control" placeholder="Search (e.g. INF)" list="symbol_list" required autocomplete="off">
                    <datalist id="symbol_list"></datalist>
                </div>

                <div class="col-md-2">
                    <label class="form-label fw-bold">2. Type</label>
                    <select name="type" id="inst_type" class="form-select">
                        <option value="CE" selected>Option (CE)</option>
                        <option value="PE">Option (PE)</option>
                        <option value="FUT">Future (FUT)</option>
                        <option value="EQ">Normal Stock (EQ)</option>
                    </select>
                </div>

                <div class="col-md-2">
                    <label class="form-label fw-bold">3. Expiry</label>
                    <select name="expiry" id="expiry_select" class="form-select">
                        <option value="" disabled selected>Select Symbol</option>
                    </select>
                </div>

                <div class="col-md-3">
                    <label class="form-label fw-bold">4. Strike <small>(Red = ATM)</small></label>
                    <select name="strike" id="strike_select" class="form-select">
                        <option value="" disabled selected>Select Expiry</option>
                    </select>
                </div>

                <div class="col-md-2">
                    <label class="form-label fw-bold">Quantity</label>
                    <div class="input-group">
                        <span class="input-group-text bg-danger text-white" id="btn-minus">-</span>
                        <input type="number" name="qty" id="qty_input" class="form-control text-center" value="0" min="1">
                        <span class="input-group-text bg-success text-white" id="btn-plus">+</span>
                    </div>
                    <small class="text-muted">Lot Size: <span id="lot-size-display">1</span></small>
                </div>

                <div class="col-md-8"></div> <div class="col-md-2">
                     <select name="mode" class="form-select fw-bold">
                        <option value="PAPER">PAPER 📝</option>
                        <option value="LIVE">LIVE 🔴</option>
                    </select>
                </div>
                <div class="col-md-2 d-grid">
                    <button type="submit" class="btn btn-warning fw-bold">EXECUTE</button>
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
                        <th>ID</th><th>Symbol</th><th>Mode</th><th>Entry</th><th>LTP</th><th>Status</th><th>Action</th>
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
    let lotSize = 1;
    let futExpiries = [];
    let optExpiries = [];

    $(document).ready(function() {
        
        // --- 1. SEARCH LOGIC ---
        let timeout = null;
        $('#symbol_search').on('input', function() {
            clearTimeout(timeout);
            let keyword = $(this).val();
            if(keyword.length < 2) return;
            timeout = setTimeout(function() {
                $.get('/api/search?q=' + keyword, function(data) {
                    $('#symbol_list').empty();
                    data.forEach(item => $('#symbol_list').append('<option value="' + item + '">'));
                });
            }, 300);
        });

        // --- 2. SYMBOL SELECTED ---
        $('#symbol_search').on('change', function() {
            let symbol = $(this).val();
            if(!symbol) return;
            
            $('#underlying-ltp').text("Loading...");
            $.get('/api/details?symbol=' + symbol, function(data) {
                currentLTP = data.ltp;
                lotSize = data.lot_size;
                futExpiries = data.fut_expiries;
                optExpiries = data.opt_expiries;

                $('#underlying-ltp').text("Spot: " + currentLTP);
                $('#lot-size-display').text(lotSize);
                $('#qty_input').val(lotSize);
                
                populateExpiries();
            });
        });

        // --- 3. TYPE/EXPIRY CHANGE LOGIC ---
        $('#inst_type').on('change', function() {
            populateExpiries();
        });

        $('#expiry_select').on('change', function() {
            updateChain();
            fetchSpecificLTP();
        });

        $('#strike_select').on('change', function() {
            fetchSpecificLTP();
        });

        // --- HELPER: POPULATE EXPIRIES ---
        function populateExpiries() {
            let type = $('#inst_type').val();
            let $exp = $('#expiry_select');
            let $strike = $('#strike_select');
            $exp.empty();

            // Handle Equity (Disable Expiry/Strike)
            if (type === 'EQ') {
                $exp.prop('disabled', true).html('<option>N/A</option>');
                $strike.prop('disabled', true).html('<option>N/A</option>');
                lotSize = 1; // EQ always 1
                $('#lot-size-display').text(lotSize);
                $('#qty_input').val(lotSize);
                fetchSpecificLTP();
                return;
            } else {
                $exp.prop('disabled', false);
                $strike.prop('disabled', false);
            }

            // Decide which expiry list to show
            let list = (type === 'FUT') ? futExpiries : optExpiries;
            
            if(list.length === 0) $exp.html('<option>No Expiries</option>');
            
            list.forEach((date, i) => {
                let label = date + (i === 0 ? " (Recent)" : "");
                $exp.append(`<option value="${date}" ${i===0 ? 'selected' : ''}>${label}</option>`);
            });

            // Trigger chain update for new expiry
            updateChain();
        }

        // --- HELPER: UPDATE CHAIN (Strikes) ---
        function updateChain() {
            let type = $('#inst_type').val();
            let symbol = $('#symbol_search').val();
            let expiry = $('#expiry_select').val();

            if(type === 'FUT' || type === 'EQ') {
                $('#strike_select').prop('disabled', true).html('<option>N/A</option>');
                fetchSpecificLTP();
                return;
            }
            
            $('#strike_select').prop('disabled', false).html('<option>Loading...</option>');

            $.get(`/api/chain?symbol=${symbol}&expiry=${expiry}&type=${type}&ltp=${currentLTP}`, function(data) {
                let $s = $('#strike_select');
                $s.empty();
                data.forEach(item => {
                    let style = item.label.includes("ATM") ? "color:red; font-weight:bold;" : "";
                    let isSel = item.label.includes("ATM") ? "selected" : "";
                    $s.append(`<option value="${item.strike}" style="${style}" ${isSel}>${item.strike} (${item.label})</option>`);
                });
                fetchSpecificLTP();
            });
        }

        // --- HELPER: FETCH SPECIFIC LTP ---
        function fetchSpecificLTP() {
            let symbol = $('#symbol_search').val();
            let type = $('#inst_type').val();
            let expiry = $('#expiry_select').val();
            let strike = $('#strike_select').val() || 0;

            if(!symbol) return;
            $('#instrument-ltp').text("Fetching...");

            $.get(`/api/specific_ltp?symbol=${symbol}&type=${type}&expiry=${expiry}&strike=${strike}`, function(data) {
                $('#instrument-ltp').text("Inst. LTP: " + data.ltp);
            });
        }

        // --- 4. QTY BUTTONS ---
        $('#btn-plus').click(function() {
            let val = parseInt($('#qty_input').val()) || 0;
            $('#qty_input').val(val + lotSize);
        });

        $('#btn-minus').click(function() {
            let val = parseInt($('#qty_input').val()) || 0;
            if (val > lotSize) $('#qty_input').val(val - lotSize);
            else $('#qty_input').val(lotSize);
        });
    });
</script>

</body>
</html>
"""

# --- ROUTES ---

@app.route('/')
def home():
    status = "ONLINE" if bot_active else "OFFLINE"
    trades = strategy_manager.load_trades()
    active = [t for t in trades if t['status'] in ['OPEN', 'PROMOTED_LIVE']]
    return render_template_string(DASHBOARD_HTML, status=status, is_active=bot_active, login_url=kite.login_url(), trades=active)

@app.route('/api/search')
def api_search():
    return jsonify(smart_trader.search_symbols(request.args.get('q', '')))

@app.route('/api/details')
def api_details():
    return jsonify(smart_trader.get_symbol_details(kite, request.args.get('symbol', '')))

@app.route('/api/chain')
def api_chain():
    return jsonify(smart_trader.get_chain_data(
        request.args.get('symbol'), request.args.get('expiry'),
        request.args.get('type'), float(request.args.get('ltp', 0))
    ))

@app.route('/api/specific_ltp')
def api_specific_ltp():
    ltp = smart_trader.get_specific_ltp(kite,
        request.args.get('symbol'), request.args.get('expiry'),
        request.args.get('strike'), request.args.get('type')
    )
    return jsonify({"ltp": ltp})

@app.route('/trade', methods=['POST'])
def place_trade():
    if not bot_active: return redirect('/')
    
    symbol = request.form['index']
    type_ = request.form['type']
    mode = request.form['mode']
    qty = int(request.form['qty'])
    
    final_sym = smart_trader.get_exact_symbol(
        symbol, request.form.get('expiry'), request.form.get('strike', 0), type_
    )
    
    if not final_sym:
        flash("❌ Contract not found")
        return redirect('/')

    # For Equity, you might want SL logic differently (percentage vs points)
    # Defaulting to 20 points for now
    strategy_manager.create_trade_direct(kite, mode, final_sym, qty, sl_points=20)
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
        except Exception as e:
            flash(f"Login Error: {e}")
    return redirect('/')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
