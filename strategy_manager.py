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

# --- HELPER: LOGGING ---
def get_time_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log_event(trade, message):
    """Adds a timestamped event to the trade log"""
    if 'logs' not in trade: trade['logs'] = []
    trade['logs'].append(f"[{get_time_str()}] {message}")

def move_to_history(trade, final_status, exit_price):
    """Moves a trade from Active to History file"""
    trade['status'] = final_status
    trade['exit_price'] = exit_price
    trade['exit_time'] = get_time_str()
    
    # Calculate Final P&L
    pnl = (exit_price - trade['entry_price']) * trade['quantity']
    if trade['symbol'].endswith('PE') and False: # Put logic handled by (Exit-Entry) usually
        pass 
    trade['pnl'] = round(pnl, 2)
    
    log_event(trade, f"Trade Closed: {final_status} @ {exit_price}")
    
    # Load History, Append, Save
    history = load_history()
    history.insert(0, trade) # Add to top
    save_history_file(history)

def get_exchange(symbol):
    if symbol.endswith("CE") or symbol.endswith("PE") or "FUT" in symbol: return "NFO"
    return "NSE"

# --- CORE FUNCTIONS ---

def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points, custom_targets, order_type, limit_price=0):
    trades = load_trades()
    entry_price = 0.0
    exchange = get_exchange(specific_symbol)
    
    # EXECUTION
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

    # TARGETS
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
        "logs": [] # EVENT LOGS
    }
    
    log_event(trade_record, f"Trade Initiated in {mode} Mode @ {entry_price}")
    
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
                log_event(trade, "Promoted to LIVE Execution")
                save_trades(trades)
                return True
            except: return False
    return False

def close_trade_manual(kite, trade_id):
    """Manually closes a trade and moves to history"""
    trades = load_trades()
    new_active_trades = []
    found = False
    
    for trade in trades:
        if trade['id'] == int(trade_id):
            found = True
            # Fetch Exit Price
            exit_price = trade['current_ltp']
            try:
                exch = trade.get('exchange', 'NFO')
                exit_price = kite.quote(f"{exch}:{trade['symbol']}")[f"{exch}:{trade['symbol']}"]["last_price"]
                
                # If LIVE, Place Sell Order
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
            
            move_to_history(trade, "MANUAL_CLOSE", exit_price)
        else:
            new_active_trades.append(trade)
            
    if found:
        save_trades(new_active_trades)
        return True
    return False

def update_risk_engine(kite):
    """Checks SL/Target and moves completed trades to history"""
    trades = load_trades()
    active_list = []
    updated = False
    
    for trade in trades:
        # Skip already closed (just in case)
        if trade['status'] not in ['OPEN', 'PROMOTED_LIVE']:
            continue

        exch = trade.get('exchange', 'NFO')
        try:
            ltp = kite.quote(f"{exch}:{trade['symbol']}")[f"{exch}:{trade['symbol']}"]["last_price"]
            trade['current_ltp'] = ltp
            updated = True
            
            trade_finished = False
            final_status = ""
            
            # 1. CHECK SL
            if ltp <= trade['sl']:
                final_status = "SL_HIT"
                log_event(trade, f"Stop Loss Hit at {ltp}")
                trade_finished = True
                
            # 2. CHECK TARGET 1 (Move SL to Cost)
            elif ltp >= trade['targets'][0] and not trade.get('t1_hit', False):
                trade['t1_hit'] = True
                trade['sl'] = trade['entry_price'] 
                log_event(trade, f"Target 1 Hit at {ltp}. SL Moved to Cost.")
                
            # 3. CHECK TARGET 2 (Log only)
            elif ltp >= trade['targets'][1] and len(trade['logs']) > 0 and "Target 2" not in trade['logs'][-1]:
                 log_event(trade, f"Target 2 Hit at {ltp}")

            # 4. CHECK FINAL TARGET (T3)
            elif ltp >= trade['targets'][2]:
                final_status = "TARGET_HIT"
                log_event(trade, f"Final Target Hit at {ltp}")
                trade_finished = True
            
            # DECISION: Move to History or Keep Active
            if trade_finished:
                # If LIVE, we should verify Order Placement here (Sell Order)
                if trade['mode'] == "LIVE":
                    try:
                        kite.place_order(tradingsymbol=trade['symbol'], exchange=exch, transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=trade['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                    except: pass
                
                move_to_history(trade, final_status, ltp)
            else:
                active_list.append(trade) # Keep in active list
                
        except: 
            active_list.append(trade) # Keep if API fails
            continue

    if updated:
        save_trades(active_list)
