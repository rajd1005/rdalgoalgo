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
<html>
<head>
    <title>Algo Commander</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <style>
        .risk-input { background-color: #f8f9fa; border: 1px solid #ced4da; font-weight: bold; color: #495057; }
        .risk-label { font-size: 0.8rem; font-weight: bold; color: #6c757d; }
    </style>
</head>
<body class="bg-light">

<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h1>🚀 Algo Commander <span class="badge bg-secondary">{{ status }}</span></h1>
        {% if not is_active %} <a href="{{ login_url }}" class="btn btn-primary">Login</a> {% else %} <button class="btn btn-success" disabled>Online</button> {% endif %}
    </div>

    {% with messages = get_flashed_messages() %}
        {% if messages %} <div class="alert alert-info">{{ messages[0] }}</div> {% endif %}
    {% endwith %}

    <div class="row">
        <div class="col-lg-8">
            <div class="card mb-4 shadow-sm border-dark">
                <div class="card-header bg-dark text-white d-flex justify-content-between">
                    <span class="fw-bold">⚡ Trade Setup</span>
                    <div>
                        <span id="underlying-ltp" class="badge bg-secondary">Spot: -</span>
                        <span id="instrument-ltp" class="badge bg-warning text-dark">Inst. LTP: 0</span>
                    </div>
                </div>
                <div class="card-body">
                    <form action="/trade" method="post" class="row g-3">
                        
                        <div class="col-md-4">
                            <label class="form-label fw-bold">1. Symbol</label>
                            <input type="text" id="symbol_search" name="index" class="form-control" placeholder="Search (e.g. BANK)" list="symbol_list" required autocomplete="off">
                            <datalist id="symbol_list"></datalist>
                        </div>

                        <div class="col-md-3">
                            <label class="form-label fw-bold">2. Type</label>
                            <select name="type" id="inst_type" class="form-select">
                                <option value="CE" selected>Option (CE)</option>
                                <option value="PE">Option (PE)</option>
                                <option value="FUT">Future (FUT)</option>
                                <option value="EQ">Stock (EQ)</option>
                            </select>
                        </div>

                        <div class="col-md-3">
                            <label class="form-label fw-bold">3. Expiry</label>
                            <select name="expiry" id="expiry_select" class="form-select"><option disabled selected>Select Symbol</option></select>
                        </div>

                        <div class="col-md-2">
                            <label class="form-label fw-bold">4. Strike</label>
                            <select name="strike" id="strike_select" class="form-select"><option disabled selected>-</option></select>
                        </div>

                        <hr class="my-3">

                        <div class="col-md-3">
                            <label class="form-label fw-bold">Quantity</label>
                            <div class="input-group">
                                <span class="input-group-text bg-danger text-white" id="btn-minus" style="cursor:pointer">-</span>
                                <input type="number" name="qty" id="qty_input" class="form-control text-center fw-bold" value="0">
                                <span class="input-group-text bg-success text-white" id="btn-plus" style="cursor:pointer">+</span>
                            </div>
                            <small>Lot Size: <span id="lot-size-display">1</span></small>
                        </div>

                        <div class="col-md-9">
                            <label class="form-label fw-bold text-primary">🎯 Risk Manager (Auto-Calc)</label>
                            <div class="row g-2">
                                <div class="col-md-2">
                                    <span class="risk-label">SL Points</span>
                                    <input type="number" id="sl_points" name="sl_points" class="form-control" value="20">
                                </div>
                                <div class="col-md-2">
                                    <span class="risk-label text-danger">Stop Loss</span>
                                    <input type="number" step="0.05" id="sl_price" name="sl_price" class="form-control risk-input text-danger">
                                </div>
                                <div class="col-md-2">
                                    <span class="risk-label text-success">Target 1</span>
                                    <input type="number" step="0.05" id="t1_price" name="t1_price" class="form-control risk-input">
                                </div>
                                <div class="col-md-2">
                                    <span class="risk-label text-success">Target 2</span>
                                    <input type="number" step="0.05" id="t2_price" name="t2_price" class="form-control risk-input">
                                </div>
                                <div class="col-md-2">
                                    <span class="risk-label text-success">Target 3</span>
                                    <input type="number" step="0.05" id="t3_price" name="t3_price" class="form-control risk-input">
                                </div>
                            </div>
                        </div>

                        <div class="col-md-8 mt-4"></div>
                        <div class="col-md-2 mt-4">
                            <select name="mode" class="form-select fw-bold border-warning">
                                <option value="PAPER">PAPER</option>
                                <option value="LIVE">LIVE 🔴</option>
                            </select>
                        </div>
                        <div class="col-md-2 d-grid mt-4">
                            <button type="submit" class="btn btn-warning fw-bold">EXECUTE</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>

        <div class="col-lg-4">
            <div class="card shadow-sm h-100">
                <div class="card-header bg-secondary text-white">📊 Active Positions</div>
                <div class="table-responsive">
                    <table class="table table-sm table-hover mb-0" style="font-size: 0.85rem;">
                        <thead><tr><th>Sym</th><th>Entry</th><th>LTP</th><th>Status</th></tr></thead>
                        <tbody>
                            {% for trade in trades %}
                            <tr class="{% if trade.mode == 'LIVE' %}table-danger{% else %}table-info{% endif %}">
                                <td>{{ trade.symbol }}</td>
                                <td>{{ trade.entry_price }}</td>
                                <td>{{ trade.current_ltp }}</td>
                                <td>{% if trade.t1_hit %}✅{% else %}{{ trade.status }}{% endif %}</td>
                            </tr>
                            {% else %}
                            <tr><td colspan="4" class="text-center">No Trades</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
    let currentLTP = 0; // Instrument LTP (not Spot)
    let lotSize = 1;
    let futExpiries = [];
    let optExpiries = [];

    $(document).ready(function() {
        
        // --- 1. SEARCH ---
        let timeout = null;
        $('#symbol_search').on('input', function() {
            clearTimeout(timeout);
            let val = $(this).val();
            if(val.length < 2) return;
            timeout = setTimeout(() => {
                $.get('/api/search?q=' + val, (data) => {
                    $('#symbol_list').empty();
                    data.forEach(item => $('#symbol_list').append('<option value="' + item + '">'));
                });
            }, 300);
        });

        $('#symbol_search').on('change', function() {
            let sym = $(this).val();
            if(!sym) return;
            $.get('/api/details?symbol=' + sym, (data) => {
                $('#symbol_search').val(data.symbol); // Auto-correct case/name
                $('#underlying-ltp').text("Spot: " + data.ltp);
                lotSize = data.lot_size;
                futExpiries = data.fut_expiries;
                optExpiries = data.opt_expiries;
                
                $('#lot-size-display').text(lotSize);
                $('#qty_input').val(lotSize);
                
                populateExpiries();
            });
        });

        // --- 2. LOGIC HANDLERS ---
        $('#inst_type').change(populateExpiries);
        $('#expiry_select').change(() => { updateChain(); fetchLTP(); });
        $('#strike_select').change(fetchLTP);
        
        // --- 3. RISK CALCULATOR ---
        // Updates whenever Instrument LTP changes OR SL Points changes
        $('#sl_points').on('input', calcRisk);

        function calcRisk() {
            let sl_pts = parseFloat($('#sl_points').val()) || 0;
            let price = currentLTP;
            
            if(price > 0) {
                $('#sl_price').val((price - sl_pts).toFixed(2));
                $('#t1_price').val((price + (sl_pts * 0.5)).toFixed(2)); // 1:0.5
                $('#t2_price').val((price + (sl_pts * 1.0)).toFixed(2)); // 1:1
                $('#t3_price').val((price + (sl_pts * 2.0)).toFixed(2)); // 1:2
            }
        }

        function populateExpiries() {
            let type = $('#inst_type').val();
            let $exp = $('#expiry_select');
            let $str = $('#strike_select');
            $exp.empty(); $str.empty();

            if (type === 'EQ') {
                $exp.prop('disabled', true).html('<option>N/A</option>');
                $str.prop('disabled', true).html('<option>N/A</option>');
                lotSize = 1; 
                $('#lot-size-display').text(1); 
                $('#qty_input').val(1);
                fetchLTP();
                return;
            } 
            
            $exp.prop('disabled', false); $str.prop('disabled', false);
            let list = (type === 'FUT') ? futExpiries : optExpiries;
            list.forEach((d, i) => $exp.append(`<option value="${d}" ${i===0?'selected':''}>${d}${i===0?' (Recent)':''}</option>`));
            updateChain();
        }

        function updateChain() {
            let type = $('#inst_type').val();
            if(type === 'FUT' || type === 'EQ') { 
                $('#strike_select').prop('disabled', true).html('<option>N/A</option>'); 
                fetchLTP(); 
                return; 
            }
            
            $('#strike_select').prop('disabled', false);
            let sym = $('#symbol_search').val();
            let exp = $('#expiry_select').val();
            // Pass Spot price for ATM calculation (approx)
            let spotText = $('#underlying-ltp').text().split(": ")[1] || 0;
            
            $.get(`/api/chain?symbol=${sym}&expiry=${exp}&type=${type}&ltp=${spotText}`, (data) => {
                let $s = $('#strike_select'); $s.empty();
                data.forEach(i => {
                    let style = i.label.includes("ATM") ? "color:red; font-weight:bold;" : "";
                    $s.append(`<option value="${i.strike}" style="${style}" ${i.label.includes("ATM")?'selected':''}>${i.strike} (${i.label})</option>`);
                });
                fetchLTP();
            });
        }

        function fetchLTP() {
            let sym = $('#symbol_search').val();
            let type = $('#inst_type').val();
            let exp = $('#expiry_select').val();
            let str = $('#strike_select').val() || 0;
            
            if(!sym) return;
            $('#instrument-ltp').text("Loading...");
            
            $.get(`/api/specific_ltp?symbol=${sym}&type=${type}&expiry=${exp}&strike=${str}`, (data) => {
                currentLTP = data.ltp;
                $('#instrument-ltp').text("Inst. LTP: " + currentLTP);
                calcRisk(); // Recalculate targets based on new LTP
            });
        }

        // Qty Buttons
        $('#btn-plus').click(() => $('#qty_input').val(parseInt($('#qty_input').val()||0) + lotSize));
        $('#btn-minus').click(() => {
            let v = parseInt($('#qty_input').val()||0);
            $('#qty_input').val(v > lotSize ? v - lotSize : lotSize);
        });
    });
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
    return render_template_string(DASHBOARD_HTML, status=status, is_active=bot_active, login_url=kite.login_url(), trades=active)

@app.route('/api/search')
def api_search(): return jsonify(smart_trader.search_symbols(request.args.get('q', '')))
@app.route('/api/details')
def api_details(): return jsonify(smart_trader.get_symbol_details(kite, request.args.get('symbol', '')))
@app.route('/api/chain')
def api_chain(): return jsonify(smart_trader.get_chain_data(request.args.get('symbol'), request.args.get('expiry'), request.args.get('type'), float(request.args.get('ltp', 0))))
@app.route('/api/specific_ltp')
def api_s_ltp(): return jsonify({"ltp": smart_trader.get_specific_ltp(kite, request.args.get('symbol'), request.args.get('expiry'), request.args.get('strike'), request.args.get('type'))})

@app.route('/trade', methods=['POST'])
def place_trade():
    if not bot_active: return redirect('/')
    
    # Get standard inputs
    sym = request.form['index']
    type_ = request.form['type']
    mode = request.form['mode']
    qty = int(request.form['qty'])
    sl_points = float(request.form['sl_points'])
    
    # Get Custom Targets (if user edited them)
    custom_targets = [
        float(request.form['t1_price']),
        float(request.form['t2_price']),
        float(request.form['t3_price']),
        float(request.form['t3_price']) + (float(request.form['t3_price']) - float(request.form['t2_price'])), # T4 (Infer)
        float(request.form['t3_price']) * 1.1 # T5 (Infer)
    ]
    
    # Get Exact Symbol
    final_sym = smart_trader.get_exact_symbol(sym, request.form.get('expiry'), request.form.get('strike', 0), type_)
    
    if not final_sym:
        flash("❌ Contract not found")
        return redirect('/')

    strategy_manager.create_trade_direct(kite, mode, final_sym, qty, sl_points, custom_targets)
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
