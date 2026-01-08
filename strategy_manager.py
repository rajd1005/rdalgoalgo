import json
import os
import time
from datetime import datetime

TRADES_FILE = 'active_trades.json'
HISTORY_FILE = 'trade_history.json'

# --- FILE OPERATIONS ---
def load_trades():
    if os.path.exists(TRADES_FILE):
        try: with open(TRADES_FILE, 'r') as f: return json.load(f)
        except: return []
    return []

def save_trades(trades):
    with open(TRADES_FILE, 'w') as f: json.dump(trades, f, default=str, indent=4)

def load_history():
    if os.path.exists(HISTORY_FILE):
        try: with open(HISTORY_FILE, 'r') as f: return json.load(f)
        except: return []
    return []

def save_history_file(history):
    with open(HISTORY_FILE, 'w') as f: json.dump(history, f, default=str, indent=4)

# --- UTILS ---
def get_time_str(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log_event(trade, message):
    if 'logs' not in trade: trade['logs'] = []
    trade['logs'].append(f"[{get_time_str()}] {message}")

def move_to_history(trade, final_status, exit_price):
    trade['status'] = final_status
    trade['exit_price'] = exit_price
    trade['exit_time'] = get_time_str()
    trade['pnl'] = round((exit_price - trade['entry_price']) * trade['quantity'], 2)
    log_event(trade, f"Closed: {final_status} @ {exit_price}")
    
    hist = load_history()
    hist.insert(0, trade)
    save_history_file(hist)

def get_exchange(symbol):
    if symbol.endswith("CE") or symbol.endswith("PE") or "FUT" in symbol: return "NFO"
    return "NSE"

# --- TRADE LOGIC ---

def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points, custom_targets, order_type, limit_price=0):
    trades = load_trades()
    exchange = get_exchange(specific_symbol)
    entry_price = 0.0
    
    if mode == "LIVE":
        try:
            k_type = kite.ORDER_TYPE_MARKET if order_type == "MARKET" else kite.ORDER_TYPE_LIMIT
            price = 0 if order_type == "MARKET" else limit_price
            kite.place_order(tradingsymbol=specific_symbol, exchange=exchange, transaction_type=kite.TRANSACTION_TYPE_BUY, quantity=quantity, order_type=k_type, price=price, product=kite.PRODUCT_MIS)
            entry_price = float(limit_price) if order_type == "LIMIT" else 0.0
        except Exception as e: return {"status": "error", "message": str(e)}
    
    if entry_price == 0:
        try: entry_price = kite.quote(f"{exchange}:{specific_symbol}")[f"{exchange}:{specific_symbol}"]["last_price"]
        except: entry_price = 100.0

    targets = custom_targets if len(custom_targets) == 3 else [entry_price+sl_points*0.5, entry_price+sl_points*1.0, entry_price+sl_points*2.0]

    record = {
        "id": int(time.time()),
        "entry_time": get_time_str(),
        "symbol": specific_symbol,
        "exchange": exchange,
        "mode": mode,
        "order_type": order_type,
        "status": "OPEN",
        "entry_price": entry_price,
        "quantity": quantity,
        "sl": entry_price - sl_points,
        "targets": targets,
        "t1_hit": False,
        "current_ltp": entry_price,
        "logs": [f"Trade Open ({mode}) @ {entry_price}"]
    }
    
    trades.append(record)
    save_trades(trades)
    return {"status": "success", "trade": record}

def inject_simulated_trade(trade_data, is_active):
    """
    Saves a historical simulation result to the correct file (Active or Closed).
    """
    # 1. Fill missing fields
    trade_data['id'] = int(time.time())
    trade_data['mode'] = "PAPER" # Historical is always Paper
    trade_data['order_type'] = "SIMULATION"
    trade_data['exchange'] = get_exchange(trade_data['symbol'])
    
    if is_active:
        # Add to Active Trades
        trades = load_trades()
        trades.append(trade_data)
        save_trades(trades)
    else:
        # Add to Closed Trades
        trade_data['pnl'] = round((trade_data['exit_price'] - trade_data['entry_price']) * trade_data['quantity'], 2)
        hist = load_history()
        hist.insert(0, trade_data)
        save_history_file(hist)

def promote_to_live(kite, trade_id):
    trades = load_trades()
    for t in trades:
        if t['id'] == int(trade_id) and t['mode'] == "PAPER":
            try:
                kite.place_order(tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_BUY, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                t['mode'] = "LIVE"
                t['status'] = "PROMOTED_LIVE"
                log_event(t, "Promoted to LIVE")
                save_trades(trades)
                return True
            except: return False
    return False

def close_trade_manual(kite, trade_id):
    trades = load_trades()
    active, found = [], False
    for t in trades:
        if t['id'] == int(trade_id):
            found = True
            exit_p = t['current_ltp']
            if t['mode'] == "LIVE":
                try: kite.place_order(tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                except: pass
            move_to_history(t, "MANUAL_EXIT", exit_p)
        else: active.append(t)
    if found: 
        save_trades(active)
        return True
    return False

def update_risk_engine(kite):
    trades = load_trades()
    active, updated = [], False
    
    for t in trades:
        if t['status'] not in ['OPEN', 'PROMOTED_LIVE']: continue
        try:
            ltp = kite.quote(f"{t['exchange']}:{t['symbol']}")[f"{t['exchange']}:{t['symbol']}"]["last_price"]
            t['current_ltp'] = ltp
            updated = True
            
            done = False
            status = ""
            
            if ltp <= t['sl']:
                status = "SL_HIT"
                log_event(t, f"SL Hit @ {ltp}")
                done = True
            elif ltp >= t['targets'][0] and not t.get('t1_hit'):
                t['t1_hit'] = True
                t['sl'] = t['entry_price']
                log_event(t, f"T1 Hit @ {ltp}. SL -> Cost")
            elif ltp >= t['targets'][2]:
                status = "TARGET_HIT"
                log_event(t, f"Target 3 Hit @ {ltp}")
                done = True
            
            if done:
                if t['mode'] == "LIVE":
                    try: kite.place_order(tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                    except: pass
                move_to_history(t, status, ltp)
            else:
                active.append(t)
        except: active.append(t)
        
    if updated: save_trades(active)
