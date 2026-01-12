import json
import time
import threading
from datetime import datetime
import pytz
from kiteconnect import KiteConnect
from database import db, ActiveTrade, TradeHistory, User

IST = pytz.timezone('Asia/Kolkata')
trade_lock = threading.Lock()
monitor_active = False

# Global Market Data (Accessed by API)
MARKET_INDICES = {
    "NIFTY": 0.0,
    "BANKNIFTY": 0.0,
    "TIMESTAMP": ""
}

def get_time_str(): return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

# --- USER HELPER ---
def get_user_kite(user):
    """Reconstructs Kite Object for a specific user"""
    if not user.broker_access_token: return None
    k = KiteConnect(api_key=user.broker_api_key)
    k.set_access_token(user.broker_access_token)
    return k

def load_trades(user_id=None):
    try:
        if user_id:
            trades_objs = ActiveTrade.query.filter_by(user_id=user_id).all()
        else:
            trades_objs = ActiveTrade.query.all()
        return [t.to_dict() for t in trades_objs]
    except Exception as e:
        print(f"Load Trades Error: {e}")
        return []

def load_history(user_id):
    try:
        return [json.loads(r.data) for r in TradeHistory.query.filter_by(user_id=user_id).order_by(TradeHistory.id.desc()).all()]
    except: return []

# --- MARKET MONITOR ---
def start_monitor(admin_kite, app):
    global monitor_active
    if monitor_active: return
    monitor_active = True
    threading.Thread(target=run_market_monitor, args=(admin_kite, app), daemon=True).start()
    print("🚀 Market Monitor Thread Started")

def run_market_monitor(admin_kite, app):
    global monitor_active
    print("✅ Risk Engine Active")
    while monitor_active:
        try:
            with app.app_context():
                update_risk_engine(admin_kite)
        except Exception as e:
            print(f"❌ Monitor Loop Error: {e}")
        time.sleep(1)

def update_risk_engine(admin_kite):
    global MARKET_INDICES
    
    # 1. Fetch All Active Trades (All Users)
    trades = ActiveTrade.query.all()
    
    # 2. Prepare List of Symbols (Always fetch Indices)
    instruments_to_fetch = ["NSE:NIFTY 50", "NSE:NIFTY BANK"]
    
    # Add active trade symbols
    if trades:
        instruments_to_fetch.extend([f"{t.exchange}:{t.symbol}" for t in trades])
    
    # Remove duplicates
    instruments_to_fetch = list(set(instruments_to_fetch))

    # 3. Fetch Live Quotes
    try: 
        live_prices = admin_kite.quote(instruments_to_fetch)
    except: return

    # 4. Update Global Indices (For Ticker API)
    if "NSE:NIFTY 50" in live_prices:
        MARKET_INDICES["NIFTY"] = live_prices["NSE:NIFTY 50"]["last_price"]
    if "NSE:NIFTY BANK" in live_prices:
        MARKET_INDICES["BANKNIFTY"] = live_prices["NSE:NIFTY BANK"]["last_price"]
    MARKET_INDICES["TIMESTAMP"] = get_time_str()

    # 5. Process Trade Logic (Only if trades exist)
    if not trades: return

    with trade_lock:
        updated = False
        for t in trades:
            inst_key = f"{t.exchange}:{t.symbol}"
            if inst_key not in live_prices: continue
            
            ltp = live_prices[inst_key]['last_price']
            t.current_ltp = ltp
            updated = True
            
            # --- EXECUTION LOGIC ---
            user = User.query.get(t.user_id)
            user_kite = None
            if t.mode == 'LIVE':
                user_kite = get_user_kite(user) # Init only if needed
            
            # PENDING -> OPEN
            if t.status == "PENDING":
                if (t.trigger_dir == 'BELOW' and ltp <= t.entry_price) or (t.trigger_dir == 'ABOVE' and ltp >= t.entry_price):
                    t.status = "OPEN"
                    t.highest_ltp = t.entry_price
                    log_event(t, f"Order ACTIVATED @ {ltp}")
                    if t.mode == 'LIVE' and user_kite:
                        try: user_kite.place_order(tradingsymbol=t.symbol, exchange=t.exchange, transaction_type=user_kite.TRANSACTION_TYPE_BUY, quantity=t.quantity, order_type=user_kite.ORDER_TYPE_MARKET, product=user_kite.PRODUCT_MIS)
                        except Exception as e: log_event(t, f"Broker Fail: {e}")
                continue

            # OPEN TRADE MANAGEMENT
            if t.status in ['OPEN', 'PROMOTED_LIVE']:
                t.highest_ltp = max(t.highest_ltp, ltp)
                
                # Deserialization
                targets = json.loads(t.targets_json)
                controls = json.loads(t.target_controls_json)
                hit_indices = json.loads(t.targets_hit_indices_json)

                # Trailing SL Logic
                if t.trailing_sl > 0:
                    new_sl = ltp - t.trailing_sl
                    limit_mode = t.sl_to_entry
                    limit_price = float('inf')
                    if limit_mode == 1: limit_price = t.entry_price
                    elif limit_mode == 2 and len(targets) > 0: limit_price = targets[0]
                    
                    if limit_mode > 0: new_sl = min(new_sl, limit_price)
                    if new_sl > t.sl:
                        t.sl = new_sl
                        log_event(t, f"Trailing SL Moved to {t.sl:.2f}")

                # Exit Logic
                exit_triggered = False; exit_reason = ""
                qty_to_exit = 0
                
                if ltp <= t.sl:
                    exit_triggered = True
                    exit_reason = "SL_HIT"
                elif not exit_triggered:
                    for i, tgt in enumerate(targets):
                        if i not in hit_indices and ltp >= tgt:
                            hit_indices.append(i)
                            t.targets_hit_indices_json = json.dumps(hit_indices)
                            conf = controls[i]
                            if not conf['enabled']: continue
                            
                            exit_lots = conf.get('lots', 0)
                            qty_to_exit = exit_lots * t.lot_size
                            
                            if qty_to_exit >= t.quantity:
                                exit_triggered = True; exit_reason = "TARGET_HIT"
                                break
                            elif qty_to_exit > 0:
                                t.quantity -= qty_to_exit
                                log_event(t, f"Target {i+1} Hit. Exited {qty_to_exit}")
                                if t.mode == 'LIVE' and user_kite:
                                    try: user_kite.place_order(tradingsymbol=t.symbol, exchange=t.exchange, transaction_type=user_kite.TRANSACTION_TYPE_SELL, quantity=qty_to_exit, order_type=user_kite.ORDER_TYPE_MARKET, product=user_kite.PRODUCT_MIS)
                                    except: pass

                if exit_triggered:
                    if t.mode == "LIVE" and user_kite:
                        try: user_kite.place_order(tradingsymbol=t.symbol, exchange=t.exchange, transaction_type=user_kite.TRANSACTION_TYPE_SELL, quantity=t.quantity, order_type=user_kite.ORDER_TYPE_MARKET, product=user_kite.PRODUCT_MIS)
                        except: pass
                    move_to_history_db(t, exit_reason, ltp)

        if updated: db.session.commit()

# --- TRADE ACTIONS ---
def create_trade_direct(admin_kite, user, mode, symbol, quantity, sl_points, custom_targets, order_type, limit_price, target_controls, trailing_sl, sl_to_entry, exit_multiplayer):
    
    exchange = "NFO"
    
    # 1. Get Live Price from ADMIN KITE
    try: current_ltp = admin_kite.quote(f"{exchange}:{symbol}")[f"{exchange}:{symbol}"]["last_price"]
    except: return {"status": "error", "message": "Market Data Error"}

    # 2. Setup Data
    status = "OPEN"; entry_price = current_ltp; trigger_dir = "BELOW"
    if order_type == "LIMIT":
        entry_price = float(limit_price)
        status = "PENDING"
        trigger_dir = "ABOVE" if entry_price >= current_ltp else "BELOW"
    
    # 3. Broker Order (If LIVE) -> Use USER KITE
    if mode == "LIVE" and status == "OPEN":
        user_kite = get_user_kite(user)
        if not user_kite: return {"status": "error", "message": "User Broker Not Connected"}
        try:
            user_kite.place_order(tradingsymbol=symbol, exchange=exchange, transaction_type=user_kite.TRANSACTION_TYPE_BUY, quantity=quantity, order_type=user_kite.ORDER_TYPE_MARKET, product=user_kite.PRODUCT_MIS)
        except Exception as e: return {"status": "error", "message": str(e)}

    # 4. Save to DB
    with trade_lock:
        new_trade = ActiveTrade(
            user_id=user.id,
            trade_ref=str(int(time.time())),
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            status=status,
            order_type=order_type,
            entry_price=entry_price,
            quantity=quantity,
            current_ltp=current_ltp,
            sl=entry_price - sl_points,
            trailing_sl=trailing_sl,
            sl_to_entry=sl_to_entry,
            exit_multiplier=exit_multiplayer,
            targets_json=json.dumps(custom_targets),
            target_controls_json=json.dumps(target_controls),
            trigger_dir=trigger_dir,
            entry_time=get_time_str()
        )
        db.session.add(new_trade)
        db.session.commit()
        return {"status": "success"}

def close_trade_manual(admin_kite, user, trade_id):
    with trade_lock:
        trade = ActiveTrade.query.filter_by(id=trade_id, user_id=user.id).first()
        if not trade: return False
        
        # Fetch exit price from Admin Kite
        try: exit_p = admin_kite.quote(f"{trade.exchange}:{trade.symbol}")[f"{trade.exchange}:{trade.symbol}"]['last_price']
        except: exit_p = trade.current_ltp

        if trade.mode == "LIVE":
            user_kite = get_user_kite(user)
            if user_kite:
                try: user_kite.place_order(tradingsymbol=trade.symbol, exchange=trade.exchange, transaction_type=user_kite.TRANSACTION_TYPE_SELL, quantity=trade.quantity, order_type=user_kite.ORDER_TYPE_MARKET, product=user_kite.PRODUCT_MIS)
                except: pass
        
        move_to_history_db(trade, "MANUAL_EXIT", exit_p)
        db.session.commit()
        return True

def log_event(trade, msg):
    try:
        logs = json.loads(trade.logs_json)
        logs.append(f"[{get_time_str()}] {msg}")
        trade.logs_json = json.dumps(logs)
    except: pass

def move_to_history_db(trade_obj, status, exit_price):
    d = trade_obj.to_dict()
    d['status'] = status
    d['exit_price'] = exit_price
    d['pnl'] = (exit_price - trade_obj.entry_price) * trade_obj.quantity
    hist = TradeHistory(user_id=trade_obj.user_id, data=json.dumps(d))
    db.session.add(hist)
    db.session.delete(trade_obj)
