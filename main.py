import os
from flask import Flask, render_template, request, redirect, flash, jsonify
from kiteconnect import KiteConnect
import config
import strategy_manager
import smart_trader

# --- INITIALIZATION ---
app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# Setup Kite Instance
kite = KiteConnect(api_key=config.API_KEY)
access_token = None
bot_active = False

# --- WEB ROUTES ---

@app.route('/')
def home():
    """
    Renders the main dashboard.
    Loads active trades from JSON to display in the Positions tab.
    """
    trades = strategy_manager.load_trades()
    # Filter to show only active trades
    active_trades = [t for t in trades if t['status'] in ['OPEN', 'PROMOTED_LIVE']]
    
    return render_template('dashboard.html', 
                           is_active=bot_active, 
                           login_url=kite.login_url(), 
                           trades=active_trades)

@app.route('/callback')
def callback():
    """
    Handles the Zerodha Redirect.
    Generates the Access Token and initializes the bot.
    """
    global access_token, bot_active
    request_token = request.args.get("request_token")
    
    if request_token:
        try:
            data = kite.generate_session(request_token, api_secret=config.API_SECRET)
            access_token = data["access_token"]
            kite.set_access_token(access_token)
            
            # Start the bot state
            if not bot_active:
                bot_active = True
                print("✅ Login Successful. Bot is Active.")
                # Pre-fetch instruments to speed up first search
                smart_trader.fetch_instruments(kite)
                
            flash("✅ System Online! Connected to Zerodha.")
        except Exception as e:
            flash(f"❌ Login Failed: {e}")
            print(f"Login Error: {e}")
            
    return redirect('/')

# --- API ROUTES (AJAX) ---

@app.route('/api/indices')
def api_indices():
    """Returns live spot prices for NIFTY, BANKNIFTY, SENSEX"""
    if not bot_active: 
        return jsonify({"NIFTY": 0, "BANKNIFTY": 0, "SENSEX": 0})
    return jsonify(smart_trader.get_indices_ltp(kite))

@app.route('/api/search')
def api_search():
    """Symbol Search Autocomplete"""
    query = request.args.get('q', '')
    return jsonify(smart_trader.search_symbols(query))

@app.route('/api/details')
def api_details():
    """Returns Lot Size, Expiries, and underlying LTP"""
    symbol = request.args.get('symbol', '')
    if not bot_active: return jsonify({})
    return jsonify(smart_trader.get_symbol_details(kite, symbol))

@app.route('/api/chain')
def api_chain():
    """Returns Option Chain Strikes with Moneyness (ATM/ITM)"""
    symbol = request.args.get('symbol')
    expiry = request.args.get('expiry')
    type_ = request.args.get('type')
    ltp = float(request.args.get('ltp', 0))
    
    return jsonify(smart_trader.get_chain_data(symbol, expiry, type_, ltp))

@app.route('/api/specific_ltp')
def api_specific_ltp():
    """Returns the LTP of the exact selected instrument (Option/Future)"""
    if not bot_active: return jsonify({"ltp": 0})
    
    ltp = smart_trader.get_specific_ltp(
        kite,
        request.args.get('symbol'),
        request.args.get('expiry'),
        request.args.get('strike'),
        request.args.get('type')
    )
    return jsonify({"ltp": ltp})

@app.route('/api/history_check')
def api_history():
    """Checks historical OHLC data for the specific past time"""
    if not bot_active: return jsonify({"status": "error", "message": "System Offline"})
    
    sym = request.args.get('symbol')
    typ = request.args.get('type')
    strk = request.args.get('strike')
    expiry = request.args.get('expiry')
    # Convert HTML datetime input (T) to Python format (space)
    time_str = request.args.get('time', '').replace('T', ' ')
    
    return jsonify(smart_trader.fetch_historical_check(kite, sym, expiry, strk, typ, time_str))

# --- TRADE EXECUTION ROUTES ---

@app.route('/trade', methods=['POST'])
def place_trade():
    """
    Handles form submission to execute a trade (Live or Paper).
    """
    if not bot_active:
        flash("❌ System is Offline. Please Login.")
        return redirect('/')
    
    try:
        # 1. Extract Basic Form Data
        symbol_common = request.form['index']
        inst_type = request.form['type']
        mode = request.form['mode']
        qty = int(request.form['qty'])
        order_type = request.form['order_type'] # MARKET or LIMIT
        
        # Handle Limit Price (might be empty string)
        limit_price_input = request.form.get('limit_price', '')
        limit_price = float(limit_price_input) if limit_price_input else 0.0
        
        # 2. Extract Risk Data
        sl_points = float(request.form.get('sl_points', 0))
        
        # Extract 3 Targets safely
        t1 = float(request.form.get('t1_price', 0))
        t2 = float(request.form.get('t2_price', 0))
        t3 = float(request.form.get('t3_price', 0))
        
        custom_targets = []
        if t1 > 0: custom_targets.append(t1)
        if t2 > 0: custom_targets.append(t2)
        if t3 > 0: custom_targets.append(t3)
        
        # 3. Resolve Exact Tradingsymbol (e.g. NIFTY24JAN21500CE)
        expiry = request.form.get('expiry')
        strike = request.form.get('strike', 0)
        
        final_symbol = smart_trader.get_exact_symbol(symbol_common, expiry, strike, inst_type)
        
        if not final_symbol:
            flash(f"❌ Contract Not Found: {symbol_common} {expiry} {strike}")
            return redirect('/')

        # 4. Send to Strategy Manager
        result = strategy_manager.create_trade_direct(
            kite, 
            mode, 
            final_symbol, 
            qty, 
            sl_points, 
            custom_targets, 
            order_type, 
            limit_price
        )
        
        if result['status'] == 'success':
            flash(f"✅ {mode} Trade Executed: {final_symbol}")
        else:
            flash(f"❌ Execution Failed: {result['message']}")

    except Exception as e:
        flash(f"❌ Critical Error: {str(e)}")
        print(f"Trade Error: {e}")
        
    return redirect('/')

@app.route('/promote/<trade_id>')
def promote(trade_id):
    """
    Promotes a Paper trade to Live execution.
    """
    if not bot_active: return redirect('/')
    
    success = strategy_manager.promote_to_live(kite, trade_id)
    if success:
        flash("✅ Position Promoted to LIVE Execution!")
    else:
        flash("❌ Promotion Failed.")
        
    return redirect('/')

# --- START SERVER ---

if __name__ == "__main__":
    # Ensure templates folder exists
    if not os.path.exists('templates'):
        print("⚠️ Warning: 'templates' folder missing. UI will not load.")
        
    app.run(host='0.0.0.0', port=config.PORT, threaded=True)
