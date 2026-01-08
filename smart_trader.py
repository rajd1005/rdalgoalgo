import json
import os
import time
from datetime import datetime

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
        current_ltp = limit_price if limit_price > 0 else 100.0

    status = "OPEN"
    entry_price = 0.0

    if order_type == "MARKET":
        entry_price = current_ltp
        status = "OPEN"
    else:
        entry_price = float(limit_price)
        if current_ltp <= entry_price:
            status = "OPEN"
            entry_price = current_ltp
        else:
            status = "PENDING"

    if mode == "LIVE":
        try:
            k_type = kite.ORDER_TYPE_MARKET if order_type == "MARKET" else kite.ORDER_TYPE_LIMIT
            price = 0 if order_type == "MARKET" else entry_price
            
            kite.place_order(
                tradingsymbol=specific_symbol,
                exchange=exchange,
                transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=quantity,
                order_type=k_type,
                price=price,
                product=kite.PRODUCT_MIS
            )
        except Exception as e:
            return {"status": "error", "message": str(e)}

    targets = []
    if len(custom_targets) == 3:
        targets = custom_targets
    else:
        targets = [
            entry_price + (sl_points * 0.5),
            entry_price + (sl_points * 1.0),
            entry_price + (sl_points * 2.0)
        ]

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
        "sl": entry_price - sl_points,
        "targets": targets,
        "t1_hit": False,
        "current_ltp": current_ltp,
        "logs": [f"Order Placed ({order_type}) @ {entry_price}. Status: {status}"]
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
    active, found = [], False
    for t in trades:
        if t['id'] == int(trade_id):
            found = True
            exit_p = t['current_ltp']
            
            if t['status'] == "PENDING":
                move_to_history(t, "CANCELLED_MANUAL", 0)
                continue

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
            
            move_to_history(t, "MANUAL_EXIT", exit_p)
        else:
            active.append(t)
    if found: 
        save_trades(active)
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
        trade_data['pnl'] = round((trade_data['exit_price'] - trade_data['entry_price']) * trade_data['quantity'], 2)
        hist = load_history()
        hist.insert(0, trade_data)
        save_history_file(hist)

def update_risk_engine(kite):
    trades = load_trades()
    active_list = []
    updated = False
    
    now = datetime.now()
    market_closed = (now.hour > 15) or (now.hour == 15 and now.minute >= 30)

    for t in trades:
        try:
            ltp = kite.quote(f"{t['exchange']}:{t['symbol']}")[f"{t['exchange']}:{t['symbol']}"]["last_price"]
            t['current_ltp'] = ltp
            updated = True
        except:
            active_list.append(t)
            continue

        if t['status'] == "PENDING":
            if market_closed:
                move_to_history(t, "CANCELLED_EOD", 0)
                continue
            
            if ltp <= t['entry_price']:
                t['status'] = "OPEN"
                log_event(t, f"Price Reached {ltp}. Order ACTIVATED.")
                active_list.append(t)
            else:
                active_list.append(t)
            continue

        if t['status'] in ['OPEN', 'PROMOTED_LIVE']:
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
                log_event(t, f"Final Target Hit @ {ltp}")
                done = True
            
            if done:
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
                move_to_history(t, status, ltp)
            else:
                active_list.append(t)
                
    if updated:
        save_trades(active_list)
