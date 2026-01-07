import os
import threading
from flask import Flask, render_template, request, redirect, flash, jsonify
from kiteconnect import KiteConnect
import config
import strategy_manager
import smart_trader

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# Setup Kite
kite = KiteConnect(api_key=config.API_KEY)
access_token = None
bot_active = False

@app.route('/')
def home():
    status = "ONLINE" if bot_active else "OFFLINE"
    trades = strategy_manager.load_trades()
    active = [t for t in trades if t['status'] in ['OPEN', 'PROMOTED_LIVE']]
    return render_template('dashboard.html', is_active=bot_active, login_url=kite.login_url(), trades=active, messages=[])

# --- API ROUTES ---
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
    sym = request.args.get('symbol')
    typ = request.args.get('type')
    strk = request.args.get('strike')
    expiry = request.args.get('expiry')
    time_str = request.args.get('time').replace('T', ' ')
    return jsonify(smart_trader.fetch_historical_check(kite, sym, expiry, strk, typ, time_str))

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
    
    custom_targets = [float(request.form['t1_price']), float(request.form['t2_price'])]
    
    final_sym = smart_trader.get_exact_symbol(sym, request.form.get('expiry'), request.form.get('strike', 0), type_)
    
    if not final_sym:
        flash("❌ Contract not found")
        return redirect('/')

    strategy_manager.create_trade_direct(kite, mode, final_sym, qty, sl_points, custom_targets, order_type, limit_price)
    flash(f"✅ Trade Executed: {final_sym}")
    return redirect('/')

@app.route('/promote/<trade_id>')
def promote(trade_id):
    if strategy_manager.promote_to_live(kite, trade_id): flash("✅ Promoted to Live!")
    else: flash("❌ Promotion Failed")
    return redirect('/')

@app.route('/callback')
def callback():
    global access_token, bot_active
    t = request.args.get("request_token")
    if t:
        try:
            data = kite.generate_session(t, api_secret=config.API_SECRET)
            access_token = data["access_token"]
            if not bot_active:
                bot_active = True
                smart_trader.fetch_instruments(kite)
        except Exception as e: flash(f"Login Error: {e}")
    return redirect('/')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=config.PORT, threaded=True)
