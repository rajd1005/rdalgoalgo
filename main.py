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

# --- DB INIT & ADMIN CHECK ---
def init_db_and_admin():
    with app.app_context():
        inspector = inspect(db.engine)
        if not inspector.has_table("user"):
            db.create_all()
            
            # Create Default Admin using Config Variables
            admin_user = config.ADMIN_USERNAME
            if not User.query.filter_by(username=admin_user).first():
                admin = User(
                    username=admin_user,
                    password=generate_password_hash(config.ADMIN_PASSWORD),
                    role='ADMIN',
                    plan='YEARLY',
                    plan_expiry=datetime.now() + timedelta(days=3650)
                )
                db.session.add(admin)
                db.session.commit()
                print(f"✅ Default Admin Created (User: {admin_user})")
        else:
            # Migration check for new columns if needed
            db.create_all()

init_db_and_admin()

# --- GLOBAL DATA KITE (ADMIN'S ZERODHA) ---
# This is used ONLY for fetching Live Data for the dashboard
admin_kite = KiteConnect(api_key=config.API_KEY)
admin_data_active = False

# --- AUTH & SINGLE DEVICE LOGIC ---
@app.before_request
def check_session():
    if current_user.is_authenticated:
        # Check if plan expired
        if current_user.plan_expiry and current_user.plan_expiry < datetime.now():
            logout_user()
            flash("❌ Subscription Expired. Contact Admin.")
            return redirect(url_for('login'))
        
        # Check Single Device
        if current_user.session_token != session.get('device_token'):
            logout_user()
            flash("⚠️ Logged in from another device.")
            return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        user = User.query.filter_by(username=u).first()
        
        if user and check_password_hash(user.password, p):
            # Generate Session Token (Single Device)
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
    u = request.form.get('username')
    p = request.form.get('password')
    plan = request.form.get('plan')
    days = int(request.form.get('days', 30))
    
    if User.query.filter_by(username=u).first():
        flash("User already exists")
    else:
        new_user = User(
            username=u,
            password=generate_password_hash(p),
            role='USER',
            plan=plan,
            plan_expiry=datetime.now() + timedelta(days=days)
        )
        db.session.add(new_user)
        db.session.commit()
        flash(f"User {u} created!")
    return redirect('/admin')

@app.route('/admin/generate_link/<int:uid>')
@login_required
def generate_auto_link(uid):
    if current_user.role != 'ADMIN': return jsonify({"error": "Unauthorized"})
    user = User.query.get(uid)
    if not user: return jsonify({"error": "User not found"})
    
    # Simple Magic Link Logic (Token valid for 1 use/short time logic omitted for brevity, using session token update)
    token = str(uuid.uuid4())
    user.session_token = token # Pre-set token
    db.session.commit()
    
    link = url_for('magic_login', token=token, uid=user.id, _external=True)
    return jsonify({"link": link})

@app.route('/magic_login/<int:uid>/<token>')
def magic_login(uid, token):
    user = User.query.get(uid)
    if user and user.session_token == token:
        session['device_token'] = token
        login_user(user)
        return redirect('/')
    return "Invalid or Expired Link"

@app.route('/admin/delete_user/<int:uid>')
@login_required
def delete_user(uid):
    if current_user.role != 'ADMIN': return redirect('/')
    if uid == current_user.id: return redirect('/admin') # Prevent self-delete
    User.query.filter_by(id=uid).delete()
    db.session.commit()
    flash("User deleted")
    return redirect('/admin')

# --- USER BROKER SETUP (For LIVE Trading) ---
@app.route('/user/broker_config', methods=['POST'])
@login_required
def user_broker_config():
    if current_user.plan == 'TRIAL':
        flash("❌ Trial users cannot add Live Accounts.")
        return redirect('/')
        
    api_key = request.form.get('api_key')
    api_secret = request.form.get('api_secret')
    
    current_user.broker_api_key = api_key
    current_user.broker_api_secret = api_secret
    db.session.commit()
    flash("✅ Broker Credentials Saved. Please Login to Zerodha now.")
    return redirect('/')

@app.route('/user/zerodha_login')
@login_required
def user_zerodha_login():
    if not current_user.broker_api_key:
        flash("⚠️ Setup Broker API Key first.")
        return redirect('/')
    
    # Redirect to User's Zerodha Login
    kite_login = KiteConnect(api_key=current_user.broker_api_key)
    return redirect(kite_login.login_url())

# --- MAIN APP ---

# Admin Auto-Login Background Process (Maintains Data Feed)
import auto_login
def maintain_admin_session():
    global admin_data_active
    while True:
        try:
            # Check Admin Connection
            try: admin_kite.quote("NSE:NIFTY 50")
            except: 
                print("🔄 [SYSTEM] Admin Data Feed Reconnecting...")
                token, err = auto_login.perform_auto_login(admin_kite)
                if token and token != "SKIP_SESSION":
                    data = admin_kite.generate_session(token, api_secret=config.API_SECRET)
                    admin_kite.set_access_token(data["access_token"])
                
                admin_data_active = True
                smart_trader.fetch_instruments(admin_kite)
                strategy_manager.start_monitor(admin_kite, app)
        except Exception as e:
            print(f"❌ [SYSTEM] Data Feed Error: {e}")
            admin_data_active = False
        time.sleep(300) # Check every 5 mins

@app.route('/')
@login_required
def home():
    # Filter trades for CURRENT USER only
    trades = strategy_manager.load_trades(current_user.id)
    for t in trades:
        t['symbol'] = smart_trader.get_display_name(t['symbol'])
    
    active = [t for t in trades if t['status'] in ['OPEN', 'PROMOTED_LIVE', 'PENDING', 'MONITORING']]
    
    # System status is now Admin's status (Data Feed)
    return render_template('dashboard.html', 
                           is_active=admin_data_active, 
                           trades=active,
                           user=current_user)

@app.route('/callback')
def callback():
    # Handles User's Zerodha Callback
    if not current_user.is_authenticated:
        # If Admin Auto-Login callback (handled by Selenium usually, but just in case)
        return "System Callback Received"
        
    t = request.args.get("request_token")
    if t:
        try:
            ukite = KiteConnect(api_key=current_user.broker_api_key)
            data = ukite.generate_session(t, api_secret=current_user.broker_api_secret)
            current_user.broker_access_token = data["access_token"]
            current_user.broker_login_date = datetime.now().strftime("%Y-%m-%d")
            db.session.commit()
            flash("✅ Your Broker Connected Successfully!")
        except Exception as e:
            flash(f"❌ Broker Login Failed: {e}")
    return redirect('/')

# --- API & TRADING (UPDATED FOR MULTI-USER) ---

@app.route('/api/search')
@login_required
def api_search():
    # Uses Admin's Kite for Data
    return jsonify(smart_trader.search_symbols(admin_kite, request.args.get('q', '')))

@app.route('/api/details')
@login_required
def api_details():
    # Uses Admin's Kite for Data
    return jsonify(smart_trader.get_symbol_details(admin_kite, request.args.get('symbol', '')))

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
    
    # Trial Restriction
    if current_user.plan == 'TRIAL' and mode == 'LIVE':
        flash("❌ Trial Users cannot place LIVE trades.")
        return redirect('/')

    # Broker Check for Live
    if mode == 'LIVE':
        today = datetime.now().strftime("%Y-%m-%d")
        if not current_user.broker_access_token or current_user.broker_login_date != today:
             flash("⚠️ Broker Not Connected or Token Expired. Please Login to Zerodha.")
             return redirect('/')

    try:
        sym = request.form['index']
        type_ = request.form['type']
        qty = int(request.form['qty'])
        order_type = request.form['order_type']
        limit_price = float(request.form.get('limit_price') or 0)
        sl_points = float(request.form.get('sl_points', 0))
        trailing_sl = float(request.form.get('trailing_sl') or 0)
        sl_to_entry = int(request.form.get('sl_to_entry', 0))
        exit_multiplayer = int(request.form.get('exit_multiplayer', 1))
        
        custom_targets = [float(request.form.get(f't{i}_price', 0)) for i in range(1, 4)]
        target_controls = []
        for i in range(1, 4):
            enabled = request.form.get(f't{i}_active') == 'on'
            lots = int(request.form.get(f't{i}_lots') or 0)
            if i == 3 and lots == 0: lots = 1000
            target_controls.append({'enabled': enabled, 'lots': lots})
        
        # Use Admin Kite to find symbol (Data)
        final_sym = smart_trader.get_exact_symbol(sym, request.form.get('expiry'), request.form.get('strike', 0), type_)
        if not final_sym: return redirect('/')

        # Execute Strategy (Pass Current User)
        res = strategy_manager.create_trade_direct(
            admin_kite, current_user, mode, final_sym, qty, sl_points, 
            custom_targets, order_type, limit_price, target_controls, 
            trailing_sl, sl_to_entry, exit_multiplayer
        )
        
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

# --- STARTUP ---
if __name__ == "__main__":
    # Start Admin Monitor Thread (Uses auto_login settings from config)
    t = threading.Thread(target=maintain_admin_session, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=config.PORT, threaded=True)
