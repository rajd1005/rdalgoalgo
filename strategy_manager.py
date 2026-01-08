import json
import os
import time
from datetime import datetime

TRADES_FILE = 'active_trades.json'
HISTORY_FILE = 'trade_history.json'

# --- FILE OPERATIONS ---
def load_trades():
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, 'r') as f: return json.load(f)
        except: return []
    return []

def save_trades(trades):
    with open(TRADES_FILE, 'w') as f: json.dump(trades, f, default=str, indent=4)

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: return json.load(f)
        except: return []
    return []

def save_history_file(history):
    with open(HISTORY_FILE, 'w') as f: json.dump(history, f, default=str, indent=4)

# --- LOGGING HELPER ---
def get_time_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log_event(trade, message):
    if 'logs' not in trade: trade['logs'] = []
    trade['logs'].append(f"[{get_time_str()}] {message}")

def move_to_history(trade, final_status, exit_price):
    trade['status'] = final_status
    trade['exit_price'] = exit_price
    trade['exit_time'] = get_time_str()
    trade['pnl'] = round((exit_price - trade['entry_price']) * trade['quantity'], 2)
    
    log_event(trade, f"Closed: {final_status} @ {exit_price}")
    
    history = load_history()
    history.insert(0, trade)
    save_history_file(history)

def get_exchange(symbol):
    if symbol.endswith("CE") or symbol.endswith("PE") or "FUT" in symbol: return "NFO"
    return "NSE"

# --- CORE FUNCTIONS ---

def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points, custom_targets, order_type, limit_price=0):
    trades = load_trades()
    entry_price = 0.0
    exchange = get_exchange(specific_symbol)
    
    # 1. EXECUTION
    if mode == "LIVE":
        try:
            k_type = kite.ORDER_TYPE_MARKET if order_type == "MARKET" else kite.ORDER_TYPE_LIMIT
            price = 0 if order_type == "MARKET" else limit_price
            
            kite.place_order(
                tradingsymbol=specific_symbol,
                exchange=exchange,
                transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=quantity,
                order_type=k_type,
                price=price,
                product=kite.PRODUCT_MIS
            )
            entry_price = float(limit_price) if order_type == "LIMIT" else 0.0
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    if entry_price == 0:
        try:
            entry_price = kite.quote(f"{exchange}:{specific_symbol}")[f"{exchange}:{specific_symbol}"]["last_price"]
        except: entry_price = 100.0

    # 2. TARGETS
    targets = []
    if custom_targets and len(custom_targets) == 3:
        targets = custom_targets
    else:
        targets = [
            entry_price + (sl_points * 0.5),
            entry_price + (sl_points * 1.0),
            entry_price + (sl_points * 2.0)
        ]

    trade_record = {
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
        "logs": []
    }
    
    log_event(trade_record, f"Trade Open ({mode}) @ {entry_price}")
    
    trades.append(trade_record)
    save_trades(trades)
    return {"status": "success", "trade": trade_record}

def promote_to_live(kite, trade_id):
    trades = load_trades()
    for trade in trades:
        if trade['id'] == int(trade_id) and trade['mode'] == "PAPER":
            try:
                kite.place_order(
                    tradingsymbol=trade['symbol'],
                    exchange=trade.get('exchange', 'NFO'),
                    transaction_type=kite.TRANSACTION_TYPE_BUY,
                    quantity=trade['quantity'],
                    order_type=kite.ORDER_TYPE_MARKET,
                    product=kite.PRODUCT_MIS
                )
                trade['mode'] = "LIVE"
                trade['status'] = "PROMOTED_LIVE" 
                log_event(trade, "Promoted to LIVE")
                save_trades(trades)
                return True
            except: return False
    return False

def close_trade_manual(kite, trade_id):
    trades = load_trades()
    new_active = []
    found = False
    
    for trade in trades:
        if trade['id'] == int(trade_id):
            found = True
            # Get Exit Price
            exit_price = trade['current_ltp']
            try:
                exch = trade.get('exchange', 'NFO')
                exit_price = kite.quote(f"{exch}:{trade['symbol']}")[f"{exch}:{trade['symbol']}"]["last_price"]
                
                if trade['mode'] == "LIVE":
                    kite.place_order(
                        tradingsymbol=trade['symbol'],
                        exchange=exch,
                        transaction_type=kite.TRANSACTION_TYPE_SELL,
                        quantity=trade['quantity'],
                        order_type=kite.ORDER_TYPE_MARKET,
                        product=kite.PRODUCT_MIS
                    )
            except: pass
            
            move_to_history(trade, "MANUAL_EXIT", exit_price)
        else:
            new_active.append(trade)
            
    if found:
        save_trades(new_active)
        return True
    return False

def update_risk_engine(kite):
    """
    Called periodically. Checks SL/Targets and Auto-Exits.
    """
    trades = load_trades()
    active_list = []
    updated = False
    
    for trade in trades:
        if trade['status'] not in ['OPEN', 'PROMOTED_LIVE']: continue

        exch = trade.get('exchange', 'NFO')
        try:
            ltp = kite.quote(f"{exch}:{trade['symbol']}")[f"{exch}:{trade['symbol']}"]["last_price"]
            trade['current_ltp'] = ltp
            updated = True
            
            finished = False
            status = ""
            
            # Risk Logic
            if ltp <= trade['sl']:
                status = "SL_HIT"
                log_event(trade, f"SL Hit @ {ltp}")
                finished = True
                
            elif ltp >= trade['targets'][0] and not trade.get('t1_hit', False):
                trade['t1_hit'] = True
                trade['sl'] = trade['entry_price']
                log_event(trade, f"T1 Hit @ {ltp}. SL -> Cost")
                
            elif ltp >= trade['targets'][2]:
                status = "TARGET_HIT"
                log_event(trade, f"Final Target Hit @ {ltp}")
                finished = True
            
            if finished:
                if trade['mode'] == "LIVE":
                    try:
                        kite.place_order(tradingsymbol=trade['symbol'], exchange=exch, transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=trade['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                    except: pass
                
                move_to_history(trade, status, ltp)
            else:
                active_list.append(trade)
                
        except: 
            active_list.append(trade)
            continue

    if updated:
        save_trades(active_list)
