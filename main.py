import os
import json
from flask import Flask, render_template, request, redirect, flash, jsonify
from kiteconnect import KiteConnect
import config
import strategy_manager
import smart_trader

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

kite = KiteConnect(api_key=config.API_KEY)
bot_active = False
SETTINGS_FILE = "settings.json"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"qty_mult": 1, "ratios": [0.5, 1.0, 1.5], "symbol_sl": {}}

def save_settings_file(data):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

@app.route('/')
def home():
    trades = strategy_manager.load_trades()
    active = [t for t in trades if t['status'] in ['OPEN', 'PROMOTED_LIVE', 'PENDING']]
    return render_template('dashboard.html', is_active=bot_active, login_url=kite.login_url(), trades=active)

@app.route('/logout')
def logout():
    global bot_active
    bot_active = False
    flash("🔌 Disconnected")
    return redirect('/')

@app.route('/callback')
def callback():
    global bot_active
    t = request.args.get("request_token")
    if t:
        try:
            data = kite.generate_session(t, api_secret=config.API_SECRET)
            kite.set_access_token(data["access_token"])
            bot_active = True
            smart_trader.fetch_instruments(kite)
            flash("✅ System Online")
        except Exception as e:
            flash(f"Login Error: {e}")
    return redirect('/')

# --- SETTINGS ---
@app.route('/api/settings/load')
def api_settings_load():
    return jsonify(load_settings())

@app.route('/api/settings/save', methods=['POST'])
def api_settings_save():
    save_settings_file(request.json)
    return jsonify({"status": "success"})

# --- API ---
@app.route('/api/positions')
def api_positions():
    if bot_active:
        strategy_manager.update_risk_engine(kite)
    return jsonify(strategy_manager.load_trades())

@app.route('/api/closed_trades')
def api_closed_trades():
    return jsonify(strategy_manager.load_history())

@app.route('/api/indices')
def api_indices():
    if not bot_active:
        return jsonify({"NIFTY":0, "BANKNIFTY":0, "SENSEX":0})
    return jsonify(smart_trader.get_indices_ltp(kite))

@app.route('/api/search')
def api_search():
    return jsonify(smart_trader.search_symbols(request.args.get('q', '')))

@app.route('/api/details')
def api_details():
    return jsonify(smart_trader.get_symbol_details(kite, request.args.get('symbol', '')))

@app.route('/api/chain')
def api_chain(): 
    return jsonify(smart_trader.get_chain_data(request.args.get('symbol'), request.args.get('expiry'), request.args.get('type'), float(request.args.get('ltp', 0))))

@app.route('/api/specific_ltp')
def api_s_ltp(): 
    return jsonify({"ltp": smart_trader.get_specific_ltp(kite, request.args.get('symbol'), request.args.get('expiry'), request.args.get('strike'), request.args.get('type'))})

@app.route('/api/history_check', methods=['POST'])
def api_history():
    if not bot_active:
        return jsonify({"status":"error", "message":"Offline"})
    data = request.json
    
    qty = int(data.get('qty', 50))
    sl_points = float(data.get('sl_points', 20))
    entry_price = float(data.get('entry_price', 0))
    
    t1 = float(data.get('t1', 0))
    t2 = float(data.get('t2', 0))
    t3 = float(data.get('t3', 0))
    custom_targets = [t1, t2, t3] if t1 > 0 else []

    result = smart_trader.simulate_trade(
        kite, 
        data['symbol'], data['expiry'], data['strike'], data['type'], 
        data['time'], sl_points, entry_price, custom_targets
    )
    
    if result['status'] == 'success':
        trade_data = result['trade_data']
        trade_data['quantity'] = qty
        trade_data['targets'] = custom_targets if custom_targets else [entry_price+sl_points*0.5, entry_price+sl_points*1.0, entry_price+sl_points*2.0]
        strategy_manager.inject_simulated_trade(trade_data, result['is_active'])
        return jsonify({"status": "success", "message": "Simulation Complete", "is_active": result['is_active']})
        
    return jsonify(result)

# --- EXECUTION ---
@app.route('/trade', methods=['POST'])
def place_trade():
    if not bot_active:
        return redirect('/')
    try:
        sym = request.form['index']
        type_ = request.form['type']
        mode = request.form['mode']
        qty = int(request.form['qty'])
        order_type = request.form['order_type']
        limit_price = float(request.form.get('limit_price') or 0)
        sl_points = float(request.form.get('sl_points', 0))
        
        t1 = float(request.form.get('t1_price', 0))
        t2 = float(request.form.get('t2_price', 0))
        t3 = float(request.form.get('t3_price', 0))
        custom_targets = [t1, t2, t3] if t1 > 0 else []
        
        final_sym = smart_trader.get_exact_symbol(sym, request.form.get('expiry'), request.form.get('strike', 0), type_)
        if not final_sym:
            return redirect('/')

        res = strategy_manager.create_trade_direct(kite, mode, final_sym, qty, sl_points, custom_targets, order_type, limit_price)
        if res['status'] == 'success':
            flash(f"✅ Order Placed: {final_sym}")
        else:
            flash(f"❌ Error: {res['message']}")
        
    except Exception as e:
        flash(f"Error: {e}")
    return redirect('/')

@app.route('/promote/<trade_id>')
def promote(trade_id):
    if strategy_manager.promote_to_live(kite, trade_id):
        flash("✅ Promoted!")
    else:
        flash("❌ Error")
    return redirect('/')

@app.route('/close_trade/<trade_id>')
def close_trade(trade_id):
    if strategy_manager.close_trade_manual(kite, trade_id):
        flash("✅ Closed")
    else:
        flash("❌ Error")
    return redirect('/')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=config.PORT, threaded=True)
