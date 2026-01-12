import os
import json
import threading
import time
from flask import Flask, render_template, request, redirect, flash, jsonify
from kiteconnect import KiteConnect
import config
import strategy_manager
import smart_trader
import settings
from database import db, TradeNotification
import auto_login 

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.from_object(config)

# Initialize Database
db.init_app(app)
with app.app_context():
    db.create_all()

kite = KiteConnect(api_key=config.API_KEY)

# --- GLOBAL STATE MANAGEMENT ---
# NOTE: These are process-local. Gunicorn workers do not share them.
# We use file-based token storage to sync workers.
bot_active = False
login_state = "IDLE" 
login_error_msg = None 
TOKEN_FILE = "access_token.txt"

def save_access_token(token):
    """Saves the access token to a file for other workers to read."""
    try:
        with open(TOKEN_FILE, "w") as f:
            f.write(token)
    except Exception as e:
        print(f"❌ Failed to save token: {e}")

def load_access_token():
    """Loads access token from file if memory is empty."""
    global bot_active
    if kite.access_token: return True # Already has token
    
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                token = f.read().strip()
                if token:
                    kite.set_access_token(token)
                    bot_active = True
                    return True
        except: pass
    return False

def run_auto_login_process():
    global bot_active, login_state, login_error_msg
    
    # Try loading existing token first
    if load_access_token():
        try:
            kite.quote("NSE:NIFTY 50")
            print("✅ Existing Token Valid. Skipping Login.")
            login_state = "IDLE"
            return
        except:
            print("⚠️ Existing Token Expired.")

    if not config.ZERODHA_USER_ID or not config.TOTP_SECRET:
        login_state = "FAILED"; login_error_msg = "Missing Credentials"; return

    login_state = "WORKING"; login_error_msg = None
    try:
        token, error = auto_login.perform_auto_login(kite)
        
        # CASE 1: Dashboard Detected (Assume session exists or token file exists)
        if token == "SKIP_SESSION":
            # If we skipped session, we MUST try to load the token from file again
            # because 'SKIP_SESSION' means the browser is logged in, but we need the API token.
            if load_access_token():
                print("✅ Auto-Login Verified: Session Active (Loaded from File).")
                bot_active = True
                login_state = "IDLE"
            else:
                # If we have no token file but browser is logged in, we are in a stuck state.
                # Usually implies manual login is needed or callback failed.
                print("⚠️ Browser Active but No Token File. Waiting for Callback...")
                login_state = "IDLE" 
            return

        # CASE 2: Token Captured
        if token and token != "SKIP_SESSION":
            try:
                data = kite.generate_session(token, api_secret=config.API_SECRET)
                access_token = data["access_token"]
                kite.set_access_token(access_token)
                save_access_token(access_token) # SAVE TO FILE
                
                bot_active = True
                smart_trader.fetch_instruments(kite)
                print("✅ Session Generated Successfully"); login_state = "IDLE"
            except Exception as e:
                if "Token is invalid" in str(e) and bot_active:
                    print("⚠️ Race Condition Solved"); login_state = "IDLE"
                else: raise e
        else:
            print(f"❌ Auto-Login Failed: {error}"); login_state = "FAILED"; login_error_msg = error
    except Exception as e:
        print(f"❌ Session Error: {e}"); login_state = "FAILED"; login_error_msg = str(e)

def background_monitor():
    global bot_active, login_state
    print("🖥️ Background Monitor Started")
    time.sleep(2)
    while True:
        try:
            # Always try to ensure we have a token
            load_access_token()

            if bot_active:
                try: 
                    with app.app_context(): strategy_manager.update_risk_engine(kite)
                except Exception as re: print(f"⚠️ Risk Engine Warning: {re}")
                
                # Health Check
                try: kite.quote("NSE:NIFTY 50")
                except Exception as e: 
                    print(f"⚠️ Health Check Failed: {e}")
                    bot_active = False
                    # If token is invalid, remove file so other workers know
                    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
            
            if not bot_active:
                if login_state == "IDLE":
                    print("🔄 Monitor: System Offline. Initiating Auto-Login...")
                    with app.app_context(): run_auto_login_process()
                elif login_state == "FAILED":
                    print("⚠️ Auto-Login previously failed. Retrying in 30s...")
                    time.sleep(30); login_state = "IDLE"
        except Exception as e: print(f"❌ Monitor Loop Error: {e}")
        time.sleep(0.5)

# --- ROUTES ---

@app.route('/')
def home():
    load_access_token() # Sync Worker
    if bot_active:
        trades = strategy_manager.load_trades()
        for t in trades: t['symbol'] = smart_trader.get_display_name(t['symbol'])
        active = [t for t in trades if t['status'] in ['OPEN', 'PROMOTED_LIVE', 'PENDING', 'MONITORING']]
        return render_template('dashboard.html', is_active=True, trades=active)
    return render_template('dashboard.html', is_active=False, state=login_state, error=login_error_msg, login_url=kite.login_url())

@app.route('/secure', methods=['GET', 'POST'])
def secure_login_page():
    if request.method == 'POST':
        if request.form.get('password') == config.ADMIN_PASSWORD:
            return redirect(kite.login_url())
        else: return render_template('secure_login.html', error="Invalid Password! Access Denied.")
    return render_template('secure_login.html')

@app.route('/api/status')
def api_status():
    load_access_token()
    return jsonify({"active": bot_active, "state": login_state, "login_url": kite.login_url()})

@app.route('/reset_connection')
def reset_connection():
    global bot_active, login_state
    bot_active = False; login_state = "IDLE"
    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
    flash("🔄 Connection Reset"); return redirect('/')

@app.route('/callback')
def callback():
    global bot_active
    t = request.args.get("request_token")
    if t:
        try:
            data = kite.generate_session(t, api_secret=config.API_SECRET)
            access_token = data["access_token"]
            kite.set_access_token(access_token)
            save_access_token(access_token) # Sync all workers
            
            bot_active = True
            smart_trader.fetch_instruments(kite)
            flash("✅ System Online")
        except Exception as e: flash(f"Login Error: {e}")
    return redirect('/')

@app.route('/api/settings/load')
def api_settings_load(): return jsonify(settings.load_settings())

@app.route('/api/settings/save', methods=['POST'])
def api_settings_save():
    if settings.save_settings_file(request.json): return jsonify({"status": "success"})
    return jsonify({"status": "error"})

@app.route('/api/notifications')
def api_get_notifications():
    notifs = TradeNotification.query.order_by(TradeNotification.id.desc()).limit(100).all()
    return jsonify([n.to_dict() for n in notifs])

@app.route('/api/notifications/clear')
def api_clear_notifications():
    try:
        db.session.query(TradeNotification).delete()
        db.session.commit()
        return jsonify({"status": "success", "message": "Logs Cleared"})
    except:
        db.session.rollback()
        return jsonify({"status": "error", "message": "Failed to clear logs"})

@app.route('/api/positions')
def api_positions():
    load_access_token()
    trades = strategy_manager.load_trades()
    for t in trades:
        t['lot_size'] = smart_trader.get_lot_size(t['symbol'])
        t['symbol'] = smart_trader.get_display_name(t['symbol'])
    return jsonify(trades)

@app.route('/api/closed_trades')
def api_closed_trades():
    trades = strategy_manager.load_history()
    for t in trades: t['symbol'] = smart_trader.get_display_name(t['symbol'])
    return jsonify(trades)

@app.route('/api/delete_trade/<trade_id>', methods=['POST'])
def api_delete_trade(trade_id):
    if strategy_manager.delete_trade(trade_id): return jsonify({"status": "success"})
    return jsonify({"status": "error"})

@app.route('/api/update_trade', methods=['POST'])
def api_update_trade():
    load_access_token()
    data = request.json
    try:
        if strategy_manager.update_trade_protection(kite, data['id'], data['sl'], data['targets'], data.get('trailing_sl', 0), data.get('entry_price'), data.get('target_controls'), data.get('sl_to_entry', 0), data.get('exit_multiplier', 1)):
            return jsonify({"status": "success"})
        else: return jsonify({"status": "error", "message": "Trade not found"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

@app.route('/api/manage_trade', methods=['POST'])
def api_manage_trade():
    load_access_token()
    data = request.json
    trade_id = data.get('id'); action = data.get('action'); lots = int(data.get('lots', 0))
    trades = strategy_manager.load_trades()
    t = next((x for x in trades if str(x['id']) == str(trade_id)), None)
    
    if t and lots > 0:
        lot_size = smart_trader.get_lot_size(t['symbol'])
        success, msg = strategy_manager.manage_trade_position(kite, trade_id, action, lot_size, lots)
        if success: return jsonify({"status": "success", "message": msg})
        else: return jsonify({"status": "error", "message": msg})
    return jsonify({"status": "error", "message": "Invalid Request"})

@app.route('/api/panic_squareoff', methods=['POST'])
def panic_squareoff():
    load_access_token()
    if not bot_active: return jsonify({"status": "error", "message": "System Offline"})
    try:
        success, msg = strategy_manager.square_off_all(kite)
        if success: return jsonify({"status": "success"})
        else: return jsonify({"status": "error", "message": msg})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

@app.route('/api/indices')
def api_indices():
    load_access_token()
    if not bot_active: return jsonify({"NIFTY":0, "BANKNIFTY":0, "SENSEX":0})
    return jsonify(smart_trader.get_indices_ltp(kite))

@app.route('/api/search')
def api_search():
    load_access_token()
    current_settings = settings.load_settings()
    allowed = current_settings.get('exchanges', None)
    return jsonify(smart_trader.search_symbols(kite, request.args.get('q', ''), allowed))

@app.route('/api/details')
def api_details(): 
    load_access_token()
    return jsonify(smart_trader.get_symbol_details(kite, request.args.get('symbol', '')))

@app.route('/api/chain')
def api_chain(): 
    load_access_token()
    return jsonify(smart_trader.get_chain_data(request.args.get('symbol'), request.args.get('expiry'), request.args.get('type'), float(request.args.get('ltp', 0))))

@app.route('/api/specific_ltp')
def api_s_ltp(): 
    load_access_token()
    return jsonify({"ltp": smart_trader.get_specific_ltp(kite, request.args.get('symbol'), request.args.get('expiry'), request.args.get('strike'), request.args.get('type'))})

@app.route('/trade', methods=['POST'])
def place_trade():
    load_access_token()
    if not bot_active: return redirect('/')
    try:
        sym = request.form['index']; type_ = request.form['type']; mode = request.form['mode']
        qty = int(request.form['qty']); order_type = request.form['order_type']
        limit_price = float(request.form.get('limit_price') or 0); sl_points = float(request.form.get('sl_points', 0))
        trailing_sl = float(request.form.get('trailing_sl') or 0); sl_to_entry = int(request.form.get('sl_to_entry', 0))
        exit_multiplayer = int(request.form.get('exit_multiplayer', 1))
        t1 = float(request.form.get('t1_price', 0)); t2 = float(request.form.get('t2_price', 0)); t3 = float(request.form.get('t3_price', 0))
        
        custom_targets = [t1, t2, t3] if exit_multiplayer > 1 else ([t1, t2, t3] if t1 > 0 else [])
        target_controls = []
        for i in range(1, 4):
            enabled = request.form.get(f't{i}_active') == 'on'; lots = int(request.form.get(f't{i}_lots') or 0)
            if i == 3 and lots == 0: lots = 1000
            target_controls.append({'enabled': enabled, 'lots': lots})
        
        final_sym = smart_trader.get_exact_symbol(sym, request.form.get('expiry'), request.form.get('strike', 0), type_)
        if not final_sym: return redirect('/')

        res = strategy_manager.create_trade_direct(kite, mode, final_sym, qty, sl_points, custom_targets, order_type, limit_price, target_controls, trailing_sl, sl_to_entry, exit_multiplayer)
        
        if res['status'] == 'success': 
            flash(f"✅ {res['message']}")
        else: 
            flash(f"❌ {res['message']}")

    except Exception as e: flash(f"Error: {e}")
    return redirect('/')

@app.route('/promote/<trade_id>')
def promote(trade_id):
    load_access_token()
    success, msg = strategy_manager.promote_to_live(kite, trade_id)
    if success: flash(f"✅ {msg}")
    else: flash(f"❌ {msg}")
    return redirect('/')

@app.route('/close_trade/<trade_id>')
def close_trade(trade_id):
    load_access_token()
    success, msg = strategy_manager.close_trade_manual(kite, trade_id)
    if success: flash(f"✅ {msg}")
    else: flash(f"❌ {msg}")
    return redirect('/')

if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    t = threading.Thread(target=background_monitor, daemon=True)
    t.start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=config.PORT, threaded=True)
