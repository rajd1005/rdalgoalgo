import os
import json
import threading
import time
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, flash, jsonify, session, url_for
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from kiteconnect import KiteConnect
from sqlalchemy import inspect
import config
import strategy_manager
import smart_trader
import settings
from database import db, User, ActiveTrade
import auto_login

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.from_object(config)
db.init_app(app)

# --- LOGIN MANAGER ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- DB INIT & ADMIN CREATION ---
def init_db_and_admin():
    with app.app_context():
        db.create_all()
        admin_user = config.ADMIN_USERNAME
        if not User.query.filter_by(username=admin_user).first():
            print(f"⚙️ Creating Default Admin: {admin_user}")
            admin = User(
                username=admin_user,
                password=generate_password_hash(config.ADMIN_PASSWORD),
                role='ADMIN',
                plan='YEARLY',
                plan_expiry=datetime.now() + timedelta(days=3650)
            )
            db.session.add(admin)
            db.session.commit()
            print("✅ Admin Created.")

init_db_and_admin()

# --- GLOBAL VARIABLES ---
admin_kite = KiteConnect(api_key=config.API_KEY)
admin_data_active = False
admin_connection_error = None

# --- AUTH ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        user = User.query.filter_by(username=u).first()
        if user and check_password_hash(user.password, p):
            token = str(uuid.uuid4())
            user.session_token = token
            db.session.commit()
            session['device_token'] = token
            login_user(user)
            return redirect('/')
        else:
            flash("Invalid Credentials")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

# --- ADMIN ROUTES ---
@app.route('/admin')
@login_required
def admin_panel():
    if current_user.role != 'ADMIN': return redirect('/')
    users = User.query.all()
    return render_template('admin_dashboard.html', users=users)

@app.route('/admin/add_user', methods=['POST'])
@login_required
def admin_add_user():
    if current_user.role != 'ADMIN': return redirect('/')
    u = request.form.get('username'); p = request.form.get('password')
    if User.query.filter_by(username=u).first():
        flash("User already exists")
    else:
        new_user = User(username=u, password=generate_password_hash(p), role='USER', plan=request.form.get('plan'), plan_expiry=datetime.now() + timedelta(days=int(request.form.get('days', 30))))
        db.session.add(new_user); db.session.commit()
        flash(f"User {u} created!")
    return redirect('/admin')

@app.route('/admin/delete_user/<int:uid>')
@login_required
def delete_user(uid):
    if current_user.role != 'ADMIN' or uid == current_user.id: return redirect('/admin')
    User.query.filter_by(id=uid).delete()
    db.session.commit()
    flash("User deleted")
    return redirect('/admin')

# --- BROKER SETUP ---
@app.route('/user/broker_config', methods=['POST'])
@login_required
def user_broker_config():
    if current_user.plan == 'TRIAL':
        flash("❌ Live Trading Disabled in Trial.")
        return redirect('/')
    current_user.broker_api_key = request.form.get('api_key')
    current_user.broker_api_secret = request.form.get('api_secret')
    db.session.commit()
    flash("✅ Credentials Saved.")
    return redirect('/')

@app.route('/user/zerodha_login')
@login_required
def user_zerodha_login():
    if not current_user.broker_api_key:
        flash("⚠️ Enter API Key first.")
        return redirect('/')
    return redirect(KiteConnect(api_key=current_user.broker_api_key).login_url())

# --- MANUAL ADMIN LOGIN ---
@app.route('/admin/manual_login_trigger')
@login_required
def admin_manual_login_trigger():
    if current_user.role != 'ADMIN': return redirect('/')
    return redirect(admin_kite.login_url())

# --- BACKGROUND MONITOR ---
def maintain_admin_session():
    global admin_data_active, admin_connection_error
    print("🖥️ System Monitor Started...")
    while True:
        try:
            if admin_data_active:
                try: 
                    admin_kite.quote("NSE:NIFTY 50")
                    time.sleep(60) 
                    continue
                except:
                    print("⚠️ Admin Connection Lost.")
                    admin_data_active = False
            
            if not admin_data_active:
                try:
                    print("🔄 Attempting Auto-Login...")
                    token, err = auto_login.perform_auto_login(admin_kite)
                    if token:
                        if token != "SKIP_SESSION":
                            data = admin_kite.generate_session(token, api_secret=config.API_SECRET)
                            admin_kite.set_access_token(data["access_token"])
                        
                        admin_data_active = True
                        admin_connection_error = None
                        smart_trader.fetch_instruments(admin_kite)
                        strategy_manager.start_monitor(admin_kite, app)
                        print("✅ System Online.")
                    else:
                        admin_connection_error = err or "Auto-Login Failed"
                        print(f"❌ Login Failed: {admin_connection_error}")
                except Exception as e:
                    admin_connection_error = str(e)
                    print(f"❌ Error: {e}")
            
            time.sleep(15) 
        except Exception as e:
            print(f"❌ Thread Error: {e}")
            time.sleep(15)

@app.route('/')
@login_required
def home():
    trades = strategy_manager.load_trades(current_user.id)
    for t in trades: t['symbol'] = smart_trader.get_display_name(t['symbol'])
    active = [t for t in trades if t['status'] in ['OPEN', 'PROMOTED_LIVE', 'PENDING', 'MONITORING']]
    return render_template('dashboard.html', is_active=admin_data_active, connection_error=admin_connection_error, trades=active, user=current_user)

@app.route('/callback')
def callback():
    t = request.args.get("request_token")
    if not t: return redirect('/')
    
    # ADMIN SYSTEM LOGIN
    if current_user.is_authenticated and current_user.role == 'ADMIN' and not admin_data_active:
        global admin_data_active, admin_connection_error
        try:
            data = admin_kite.generate_session(t, api_secret=config.API_SECRET)
            admin_kite.set_access_token(data["access_token"])
            admin_data_active = True
            admin_connection_error = None
            smart_trader.fetch_instruments(admin_kite)
            strategy_manager.start_monitor(admin_kite, app)
            flash("✅ System Online (Manual)")
        except Exception as e: flash(f"❌ System Login Failed: {e}")
        return redirect('/')

    # USER LOGIN
    if current_user.is_authenticated:
        try:
            ukite = KiteConnect(api_key=current_user.broker_api_key)
            data = ukite.generate_session(t, api_secret=current_user.broker_api_secret)
            current_user.broker_access_token = data["access_token"]
            current_user.broker_login_date = datetime.now().strftime("%Y-%m-%d")
            db.session.commit()
            flash("✅ Broker Connected!")
        except Exception as e: flash(f"❌ Broker Login Failed: {e}")
    
    return redirect('/')

# --- API & TRADING ROUTES ---
@app.route('/api/search')
@login_required
def api_search(): return jsonify(smart_trader.search_symbols(admin_kite, request.args.get('q', '')))

@app.route('/api/details')
@login_required
def api_details(): return jsonify(smart_trader.get_symbol_details(admin_kite, request.args.get('symbol', '')))

@app.route('/api/positions')
@login_required
def api_positions():
    trades = strategy_manager.load_trades(current_user.id)
    for t in trades: t['symbol'] = smart_trader.get_display_name(t['symbol'])
    return jsonify(trades)

@app.route('/api/closed_trades')
@login_required
def api_closed_trades():
    trades = strategy_manager.load_history(current_user.id)
    for t in trades: t['symbol'] = smart_trader.get_display_name(t['symbol'])
    return jsonify(trades)

@app.route('/trade', methods=['POST'])
@login_required
def place_trade():
    mode = request.form['mode']
    if current_user.plan == 'TRIAL' and mode == 'LIVE':
        flash("❌ Live Trading disabled in Trial."); return redirect('/')
    
    if mode == 'LIVE':
        if not current_user.broker_access_token: flash("⚠️ Broker Not Connected."); return redirect('/')

    try:
        sym = request.form['index']; type_ = request.form['type']; qty = int(request.form['qty'])
        order_type = request.form['order_type']; limit_price = float(request.form.get('limit_price') or 0)
        sl_points = float(request.form.get('sl_points', 0)); trailing_sl = float(request.form.get('trailing_sl') or 0)
        sl_to_entry = int(request.form.get('sl_to_entry', 0)); exit_multiplayer = int(request.form.get('exit_multiplayer', 1))
        
        custom_targets = [float(request.form.get(f't{i}_price', 0)) for i in range(1, 4)]
        target_controls = []
        for i in range(1, 4):
            enabled = request.form.get(f't{i}_active') == 'on'
            lots = int(request.form.get(f't{i}_lots') or 0)
            if i == 3 and lots == 0: lots = 1000
            target_controls.append({'enabled': enabled, 'lots': lots})
        
        final_sym = smart_trader.get_exact_symbol(sym, request.form.get('expiry'), request.form.get('strike', 0), type_)
        if not final_sym: return redirect('/')

        res = strategy_manager.create_trade_direct(admin_kite, current_user, mode, final_sym, qty, sl_points, custom_targets, order_type, limit_price, target_controls, trailing_sl, sl_to_entry, exit_multiplayer)
        if res['status'] == 'success': flash(f"✅ Order Placed: {final_sym}")
        else: flash(f"❌ Error: {res['message']}")
    except Exception as e: flash(f"Error: {e}")
    return redirect('/')

@app.route('/close_trade/<trade_id>')
@login_required
def close_trade(trade_id):
    if strategy_manager.close_trade_manual(admin_kite, current_user, trade_id): flash("✅ Closed")
    else: flash("❌ Error")
    return redirect('/')

if __name__ == "__main__":
    t = threading.Thread(target=maintain_admin_session, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=config.PORT, threaded=True)
