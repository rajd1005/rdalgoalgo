import os
from flask import Flask, render_template, request, redirect, flash, jsonify
from kiteconnect import KiteConnect
import config
import strategy_manager
import smart_trader

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# Setup Kite
kite = KiteConnect(api_key=config.API_KEY)
bot_active = False

@app.route('/')
def home():
    trades = strategy_manager.load_trades()
    active_trades = [t for t in trades if t['status'] in ['OPEN', 'PROMOTED_LIVE']]
    return render_template('dashboard.html', is_active=bot_active, login_url=kite.login_url(), trades=active_trades)

@app.route('/callback')
def callback():
    global bot_active
    t = request.args.get("request_token")
    if t:
        try:
            data = kite.generate_session(t, api_secret=config.API_SECRET)
            kite.set_access_token(data["access_token"])
            bot_active = True
            # Trigger Download
            smart_trader.fetch_instruments(kite)
            flash("✅ Login Successful! System Online.")
        except Exception as e: flash(f"Login Error: {e}")
    return redirect('/')

# --- API ROUTES ---
@app.route('/api/indices')
def api_indices():
    if not bot_active: return jsonify({"NIFTY":0, "BANKNIFTY":0, "SENSEX":0})
    return jsonify(smart_trader.get_indices_ltp(kite))

@app.route('/api/search')
def api_search(): return jsonify(smart_trader.search_symbols(request.args.get('q', '')))

@app.route('/api/details')
def api_details(): return jsonify(smart_trader.get_symbol_details(kite, request.args.get('symbol', '')))

@app.route('/api/chain')
def api_chain(): 
    return jsonify(smart_trader.get_chain_data(
        request.args.get('symbol'), request.args.get('expiry'), 
        request.args.get('type'), float(request.args.get('ltp', 0))
    ))

@app.route('/api/specific_ltp')
def api_s_ltp(): 
    return jsonify({"ltp": smart_trader.get_specific_ltp(
        kite, request.args.get('symbol'), request.args.get('expiry'), 
        request.args.get('strike'), request.args.get('type')
    )})

@app.route('/api/history_check')
def api_history():
    return jsonify(smart_trader.fetch_historical_check(
        kite, request.args.get('symbol'), request.args.get('expiry'), 
        request.args.get('strike'), request.args.get('type'), request.args.get('time')
    ))

# --- EXECUTION ---
@app.route('/trade', methods=['POST'])
def place_trade():
    if not bot_active: return redirect('/')
    
    try:
        # Extract Form Data
        sym = request.form['index']
        type_ = request.form['type']
        mode = request.form['mode']
        qty = int(request.form['qty'])
        order_type = request.form['order_type']
        limit_price = float(request.form.get('limit_price') or 0)
        sl_points = float(request.form.get('sl_points', 0))
        
        # Targets
        t1 = float(request.form.get('t1_price', 0))
        t2 = float(request.form.get('t2_price', 0))
        t3 = float(request.form.get('t3_price', 0))
        custom_targets = [t1, t2, t3] if t1 > 0 else []
        
        # Symbol Resolution
        final_sym = smart_trader.get_exact_symbol(sym, request.form.get('expiry'), request.form.get('strike', 0), type_)
        
        if not final_sym:
            flash("❌ Contract Not Found")
            return redirect('/')

        res = strategy_manager.create_trade_direct(kite, mode, final_sym, qty, sl_points, custom_targets, order_type, limit_price)
        
        if res['status'] == 'success': flash(f"✅ Executed: {final_sym}")
        else: flash(f"❌ Error: {res['message']}")
        
    except Exception as e:
        flash(f"Error: {e}")

    return redirect('/')

@app.route('/promote/<trade_id>')
def promote(trade_id):
    if strategy_manager.promote_to_live(kite, trade_id): flash("✅ Promoted!")
    else: flash("❌ Failed")
    return redirect('/')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=config.PORT, threaded=True)
