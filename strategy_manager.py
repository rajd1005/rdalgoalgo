import json
import os
import time
from datetime import datetime
import pandas as pd

TRADES_FILE = 'active_trades.json'
HISTORY_FILE = 'trade_history.json'

def load_trades():
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_trades(trades):
    with open(TRADES_FILE, 'w') as f:
        json.dump(trades, f, default=str, indent=4)

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_history_file(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, default=str, indent=4)

def get_time_str():
    try:
        return pd.Timestamp.now('Asia/Kolkata').strftime("%Y-%m-%d %H:%M:%S")
    except:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log_event(trade, message):
    if 'logs' not in trade:
        trade['logs'] = []
    trade['logs'].append(f"[{get_time_str()}] {message}")

def move_to_history(trade, final_status, exit_price):
    trade['status'] = final_status
    trade['exit_price'] = exit_price
    trade['exit_time'] = get_time_str()
    trade['pnl'] = round((exit_price - trade['entry_price']) * trade['quantity'], 2)
    
    # Ensure closure log if not present
    if "Closed:" not in str(trade['logs']):
         log_event(trade, f"Closed: {final_status} @ {exit_price}")
    
    history = load_history()
    history.insert(0, trade)
    save_history_file(history)

def get_exchange(symbol):
    if symbol.endswith("CE") or symbol.endswith("PE") or "FUT" in symbol:
        return "NFO"
    return "NSE"

def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points, custom_targets, order_type, limit_price=0):
    trades = load_trades()
    exchange = get_exchange(specific_symbol)
    
    current_ltp = 0.0
    try:
        current_ltp = kite.quote(f"{exchange}:{specific_symbol}")[f"{exchange}:{specific_symbol}"]["last_price"]
    except:
        current_ltp = 0.0

    if current_ltp == 0:
        return {"status": "error", "message": "Failed to fetch Live Price"}

    status = "OPEN"
    entry_price = 0.0
    trigger_dir = "BELOW" 

    if order_type == "MARKET":
        entry_price = current_ltp
        status = "OPEN"
    else:
        entry_price = float(limit_price)
        if entry_price <= 0:
            return {"status": "error", "message": "Invalid Limit Price"}

        status = "PENDING"
        if entry_price >= current_ltp:
            trigger_dir = "ABOVE"
        else:
            trigger_dir = "BELOW"

    if mode == "LIVE" and status == "OPEN":
        try:
            kite.place_order(
                tradingsymbol=specific_symbol,
                exchange=exchange,
                transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=quantity,
                order_type=kite.ORDER_TYPE_MARKET,
                price=0,
                product=kite.PRODUCT_MIS
            )
        except Exception as e:
            return {"status": "error", "message": str(e)}

    targets = []
    calc_price = entry_price
    
    if len(custom_targets) == 3:
        targets = custom_targets
    else:
        targets = [
            calc_price + (sl_points * 0.5),
            calc_price + (sl_points * 1.0),
            calc_price + (sl_points * 2.0)
        ]

    logs = [f"[{get_time_str()}] Trade Added to System"]
    logs.append(f"[{get_time_str()}] Order Created ({order_type}). Status: {status}. Trigger: {trigger_dir if order_type=='LIMIT' else 'N/A'}")
    
    if status == "OPEN":
        logs.append(f"[{get_time_str()}] Trade Activated/Entered @ {entry_price}")

    record = {
        "id": int(time.time()),
        "entry_time": get_time_str(),
        "symbol": specific_symbol,
        "exchange": exchange,
        "mode": mode,
        "order_type": order_type,
        "status": status,
        "entry_price": entry_price,
        "quantity": quantity,
        "sl": calc_price - sl_points,
        "targets": targets,
        "targets_hit_indices": [],
        "highest_ltp": entry_price, # Track Made High
        "high_locked": False,       # Flag to freeze Made High on return to entry
        "current_ltp": current_ltp,
        "trigger_dir": trigger_dir,
        "logs": logs
    }
    
    trades.append(record)
    save_trades(trades)
    return {"status": "success", "trade": record}

def promote_to_live(kite, trade_id):
    trades = load_trades()
    for t in trades:
        if t['id'] == int(trade_id) and t['mode'] == "PAPER":
            try:
                kite.place_order(
                    tradingsymbol=t['symbol'],
                    exchange=t['exchange'],
                    transaction_type=kite.TRANSACTION_TYPE_BUY,
                    quantity=t['quantity'],
                    order_type=kite.ORDER_TYPE_MARKET,
                    product=kite.PRODUCT_MIS
                )
                t['mode'] = "LIVE"
                t['status'] = "PROMOTED_LIVE"
                log_event(t, "Promoted to LIVE")
                save_trades(trades)
                return True
            except:
                return False
    return False

def close_trade_manual(kite, trade_id):
    trades = load_trades()
    active_list = []
    found = False
    
    for t in trades:
        if t['id'] == int(trade_id):
            found = True
            
            if t['status'] == "PENDING":
                move_to_history(t, "CANCELLED_MANUAL", 0)
                continue

            # Switch to MONITORING
            exit_p = t.get('current_ltp', 0)
            if t['mode'] == "LIVE" and t['status'] not in ["MONITORING"]:
                try:
                    kite.place_order(
                        tradingsymbol=t['symbol'],
                        exchange=t['exchange'],
                        transaction_type=kite.TRANSACTION_TYPE_SELL,
                        quantity=t['quantity'],
                        order_type=kite.ORDER_TYPE_MARKET,
                        product=kite.PRODUCT_MIS
                    )
                except:
                    pass
            
            t['status'] = "MONITORING"
            t['exit_price'] = exit_p
            t['exit_type'] = "MANUAL_EXIT"
            log_event(t, f"Manual Exit Initiated @ {exit_p}. Monitoring for Made High.")
            active_list.append(t)
            
        else:
            active_list.append(t)
            
    if found: 
        save_trades(active_list)
        return True
    return False

def inject_simulated_trade(trade_data, is_active):
    trade_data['id'] = int(time.time())
    trade_data['mode'] = "PAPER"
    trade_data['order_type'] = "SIMULATION"
    trade_data['exchange'] = get_exchange(trade_data['symbol'])
    if is_active:
        trades = load_trades()
        trades.append(trade_data)
        save_trades(trades)
    else:
        # Trade completely finished in simulator
        trade_data['pnl'] = round((trade_data['exit_price'] - trade_data['entry_price']) * trade_data['quantity'], 2)
        hist = load_history()
        hist.insert(0, trade_data)
        save_history_file(hist)

def update_risk_engine(kite):
    trades = load_trades()
    active_list = []
    updated = False
    
    try:
        now = pd.Timestamp.now('Asia/Kolkata')
    except:
        now = datetime.now()

    # Market Close check (3:30 PM IST)
    market_closed = (now.hour > 15) or (now.hour == 15 and now.minute >= 30)

    for t in trades:
        try:
            ltp = kite.quote(f"{t['exchange']}:{t['symbol']}")[f"{t['exchange']}:{t['symbol']}"]["last_price"]
            t['current_ltp'] = ltp
            updated = True
            
            # --- MADE HIGH LOGIC (Refined) ---
            if 'highest_ltp' not in t: t['highest_ltp'] = t['entry_price']
            if 'high_locked' not in t: t['high_locked'] = False
            
            # If not locked, track the High
            if not t['high_locked']:
                if ltp > t['highest_ltp']:
                    t['highest_ltp'] = ltp
                
                # Check Reversal to Entry: If it comes back to Entry (and had gone up), Lock it.
                if ltp <= t['entry_price'] and t['highest_ltp'] > t['entry_price']:
                     t['high_locked'] = True
                     # Note: We don't log here to avoid spamming, will log final at exit
            
        except:
            active_list.append(t)
            continue

        # --- MONITORING MODE (Post-Exit) ---
        if t['status'] == "MONITORING":
            if market_closed:
                # Finalize Trade with Made High Log
                profit = round((t['highest_ltp'] - t['entry_price']) * t['quantity'], 2)
                log_event(t, f"Market Closed. Final Made High: {t['highest_ltp']} (Max Potential Profit: ₹ {profit})")
                
                final_status = t.get('exit_type', 'CLOSED')
                exit_p = t.get('exit_price', ltp)
                
                move_to_history(t, final_status, exit_p)
                # Removed from active list
            else:
                active_list.append(t)
            continue

        # --- PENDING ORDERS ---
        if t['status'] == "PENDING":
            if market_closed:
                move_to_history(t, "CANCELLED_EOD", 0)
                continue
            
            should_activate = False
            trigger_dir = t.get('trigger_dir', 'BELOW')
            
            if trigger_dir == 'BELOW' and ltp <= t['entry_price']:
                should_activate = True
            elif trigger_dir == 'ABOVE' and ltp >= t['entry_price']:
                should_activate = True

            if should_activate:
                t['status'] = "OPEN"
                t['highest_ltp'] = t['entry_price'] 
                t['high_locked'] = False
                log_event(t, f"Price Reached {ltp}. Order ACTIVATED.")
                log_event(t, f"Trade Activated/Entered @ {ltp}") 
                if t['mode'] == 'LIVE':
                    try:
                        kite.place_order(
                            tradingsymbol=t['symbol'],
                            exchange=t['exchange'],
                            transaction_type=kite.TRANSACTION_TYPE_BUY,
                            quantity=t['quantity'],
                            order_type=kite.ORDER_TYPE_MARKET,
                            product=kite.PRODUCT_MIS
                        )
                        log_event(t, "Broker Order Placed (Market)")
                    except Exception as e:
                        log_event(t, f"Broker Order Failed: {str(e)}")
                active_list.append(t)
            else:
                active_list.append(t)
            continue

        # --- OPEN TRADES ---
        if t['status'] in ['OPEN', 'PROMOTED_LIVE']:
            exit_triggered = False
            exit_reason = ""
            exit_p = ltp
            
            # 1. Check SL (Standard OR Cost)
            if ltp <= t['sl']:
                exit_triggered = True
                exit_p = t['sl']
                
                # Check if this was a Cost Exit (SL at Entry) or Loss Exit
                if t['sl'] >= t['entry_price']:
                    exit_reason = "COST_EXIT"
                    log_event(t, f"Price returned to Entry/Cost @ {ltp}. Safe Exit triggered.")
                else:
                    exit_reason = "SL_HIT"
                    log_event(t, f"SL Hit @ {ltp}")

            # 2. Check Targets
            if not exit_triggered:
                if 'targets_hit_indices' not in t: t['targets_hit_indices'] = []
                
                for i, tgt in enumerate(t['targets']):
                    if i not in t['targets_hit_indices'] and ltp >= tgt:
                        t['targets_hit_indices'].append(i)
                        log_event(t, f"Target {i+1} Hit @ {tgt}")
                        
                        # --- UPDATE SL LOGIC: T1 HIT -> MOVE SL TO ENTRY ---
                        if i == 0:
                            t['sl'] = t['entry_price']
                            log_event(t, "T1 Hit. SL Moved to Entry Price (Cost Protection).")
                        # -----------------------------------------------
                        
                        if i == len(t['targets']) - 1:
                            exit_reason = "TARGET_HIT"
                            log_event(t, f"Final Target Hit @ {ltp}")
                            exit_triggered = True
                            exit_p = tgt
            
            if exit_triggered:
                if t['mode'] == "LIVE":
                    try:
                        kite.place_order(
                            tradingsymbol=t['symbol'],
                            exchange=t['exchange'],
                            transaction_type=kite.TRANSACTION_TYPE_SELL,
                            quantity=t['quantity'],
                            order_type=kite.ORDER_TYPE_MARKET,
                            product=kite.PRODUCT_MIS
                        )
                    except:
                        pass
                
                # Move to MONITORING instead of History
                t['status'] = "MONITORING"
                t['exit_price'] = exit_p
                t['exit_type'] = exit_reason
                log_event(t, f"Trade Exited ({exit_reason}). Made High was {t.get('highest_ltp', 0)}. Monitoring...")
                active_list.append(t)
            else:
                active_list.append(t)
                
    if updated:
        save_trades(active_list)
