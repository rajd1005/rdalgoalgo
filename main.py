import os
import json
from flask import Flask, render_template, request, redirect, flash, jsonify
from kiteconnect import KiteConnect
import config
import strategy_manager
import smart_trader
import settings
from database import db

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.from_object(config)

# Initialize Database
db.init_app(app)
with app.app_context():
    db.create_all()

kite = KiteConnect(api_key=config.API_KEY)
bot_active = False

@app.route('/')
def home():
    trades = strategy_manager.load_trades()
    # Format symbol for display
    for t in trades:
        t['symbol'] = smart_trader.get_display_name(t['symbol'])
        
    active = [t for t in trades if t['status'] in ['OPEN', 'PROMOTED_LIVE', 'PENDING', 'MONITORING']]
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

# --- SETTINGS API ---
@app.route('/api/settings/load')
def api_settings_load():
    return jsonify(settings.load_settings())

@app.route('/api/settings/save', methods=['POST'])
def api_settings_save():
    if settings.save_settings_file(request.json):
        return jsonify({"status": "success"})
    return jsonify({"status": "error"})

# --- TRADE MANAGEMENT API ---
@app.route('/api/positions')
def api_positions():
    if bot_active:
        strategy_manager.update_risk_engine(kite)
    
    trades = strategy_manager.load_trades()
    # Format symbol for display
    for t in trades:
        t['lot_size'] = smart_trader.get_lot_size(t['symbol']) # Add Lot Size info
        t['symbol'] = smart_trader.get_display_name(t['symbol'])
        
    return jsonify(trades)

@app.route('/api/closed_trades')
def api_closed_trades():
    trades = strategy_manager.load_history()
    # Format symbol for display
    for t in trades:
        t['symbol'] = smart_trader.get_display_name(t['symbol'])
        
    return jsonify(trades)

@app.route('/api/delete_trade/<trade_id>', methods=['POST'])
def api_delete_trade(trade_id):
    if strategy_manager.delete_trade(trade_id):
        return jsonify({"status": "success"})
    return jsonify({"status": "error"})

@app.route('/api/update_trade', methods=['POST'])
def api_update_trade():
    data = request.json
    try:
        if strategy_manager.update_trade_protection(
            data['id'], 
            data['sl'], 
            data['targets'], 
            data.get('trailing_sl', 0),
            data.get('entry_price'),
            data.get('target_controls'),
            data.get('sl_to_entry', 0)
        ):
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error", "message": "Trade not found"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/manage_trade', methods=['POST'])
def api_manage_trade():
    data = request.json
    trade_id = data.get('id')
    action = data.get('action') # ADD or EXIT
    lots = int(data.get('lots', 0))
    
    trades = strategy_manager.load_trades()
    t = next((x for x in trades if str(x['id']) == str(trade_id)), None)
    
    if t and lots > 0:
        lot_size = smart_trader.get_lot_size(t['symbol'])
        
        if strategy_manager.manage_trade_position(kite, trade_id, action, lot_size, lots):
             return jsonify({"status": "success"})
    
    return jsonify({"status": "error", "message": "Action Failed"})

# --- MARKET DATA API ---
@app.route('/api/indices')
def api_indices():
    if not bot_active:
        return jsonify({"NIFTY":0, "BANKNIFTY":0, "SENSEX":0})
    return jsonify(smart_trader.get_indices_ltp(kite))

@app.route('/api/search')
def api_search():
    current_settings = settings.load_settings()
    allowed = current_settings.get('exchanges', None)
    return jsonify(smart_trader.search_symbols(kite, request.args.get('q', ''), allowed))

@app.route('/api/details')
def api_details():
    return jsonify(smart_trader.get_symbol_details(kite, request.args.get('symbol', '')))

@app.route('/api/chain')
def api_chain(): 
    return jsonify(smart_trader.get_chain_data(request.args.get('symbol'), request.args.get('expiry'), request.args.get('type'), float(request.args.get('ltp', 0))))

@app.route('/api/specific_ltp')
def api_s_ltp(): 
    return jsonify({"ltp": smart_trader.get_specific_ltp(kite, request.args.get('symbol'), request.args.get('expiry'), request.args.get('strike'), request.args.get('type'))})

# --- SIMULATION & EXECUTION ---
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
    
    # New Fields
    trailing_sl = float(data.get('trailing_sl') or 0)
    sl_to_entry = int(data.get('sl_to_entry', 0))
    target_controls = data.get('target_controls', None)
    
    # UPDATE: Enforce T3 Default = Exit All (1000) if 0 in controls
    if target_controls and len(target_controls) >= 3:
        if target_controls[2]['lots'] == 0:
            target_controls[2]['lots'] = 1000

    result = smart_trader.simulate_trade(
        kite, 
        data['symbol'], data['expiry'], data['strike'], data['type'], 
        data['time'], sl_points, entry_price, custom_targets, 
        qty, trailing_sl, sl_to_entry, target_controls
    )
    
    if result['status'] == 'success':
        trade_data = result['trade_data']
        trade_data['quantity'] = qty
        trade_data['targets'] = custom_targets if custom_targets else [entry_price+sl_points*0.5, entry_price+sl_points*1.0, entry_price+sl_points*2.0]
        
        trade_data['raw_params'] = {
            'symbol': data['symbol'],
            'expiry': data['expiry'],
            'strike': data['strike'],
            'type': data['type'],
            'time': data['time']
        }
        
        strategy_manager.inject_simulated_trade(trade_data, result['is_active'])
        return jsonify({"status": "success", "message": "Simulation Complete", "is_active": result['is_active']})
        
    return jsonify(result)

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
        
        # New Trailing SL Inputs
        trailing_sl = float(request.form.get('trailing_sl') or 0)
        sl_to_entry = int(request.form.get('sl_to_entry', 0))
        
        # New Exit Multiplier
        exit_multiplayer = int(request.form.get('exit_multiplayer', 1))

        t1 = float(request.form.get('t1_price', 0))
        t2 = float(request.form.get('t2_price', 0))
        t3 = float(request.form.get('t3_price', 0))
        
        # Pass targets if Exit Multiplier is used OR if T1 is set
        if exit_multiplayer > 1:
            custom_targets = [t1, t2, t3] 
        else:
            custom_targets = [t1, t2, t3] if t1 > 0 else []
        
        # New Target Controls from Form
        target_controls = []
        for i in range(1, 4):
            enabled = request.form.get(f't{i}_active') == 'on'
            lots = int(request.form.get(f't{i}_lots') or 0)
            
            # UPDATE: Enforce T3 Default = Exit All (1000) if 0
            if i == 3 and lots == 0:
                lots = 1000
                
            target_controls.append({'enabled': enabled, 'lots': lots})
        
        final_sym = smart_trader.get_exact_symbol(sym, request.form.get('expiry'), request.form.get('strike', 0), type_)
        if not final_sym:
            return redirect('/')

        res = strategy_manager.create_trade_direct(kite, mode, final_sym, qty, sl_points, custom_targets, order_type, limit_price, target_controls, trailing_sl, sl_to_entry, exit_multiplayer)
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
