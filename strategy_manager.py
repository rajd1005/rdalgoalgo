import json
import time
from datetime import datetime, timedelta
import pandas as pd
import pytz
from database import db, ActiveTrade, TradeHistory

IST = pytz.timezone('Asia/Kolkata')

def load_trades():
    try:
        return [json.loads(r.data) for r in ActiveTrade.query.all()]
    except Exception as e:
        print(f"Load Trades Error: {e}")
        return []

def save_trades(trades):
    try:
        db.session.query(ActiveTrade).delete()
        for t in trades: db.session.add(ActiveTrade(data=json.dumps(t)))
        db.session.commit()
    except Exception as e:
        print(f"Save Trades Error: {e}")
        db.session.rollback()

def load_history():
    try:
        return [json.loads(r.data) for r in TradeHistory.query.order_by(TradeHistory.id.desc()).all()]
    except: return []

def delete_trade(trade_id):
    try:
        TradeHistory.query.filter_by(id=int(trade_id)).delete()
        db.session.commit()
        return True
    except:
        db.session.rollback()
        return False

def update_trade_protection(trade_id, sl, targets, trailing_sl=0, entry_price=None):
    trades = load_trades()
    updated = False
    for t in trades:
        if str(t['id']) == str(trade_id):
            old_sl = t['sl']
            
            entry_msg = ""
            if entry_price is not None:
                new_entry = float(entry_price)
                if new_entry != t['entry_price']:
                    old_entry = t['entry_price']
                    t['entry_price'] = new_entry
                    entry_msg = f" | Entry {old_entry} -> {new_entry}"
            
            t['sl'] = float(sl)
            t['targets'] = [float(x) for x in targets]
            t['trailing_sl'] = float(trailing_sl) if trailing_sl else 0
            
            log_event(t, f"Manual Update: SL {old_sl} -> {t['sl']}{entry_msg}. Targets: {t['targets']}. Trail: {t['trailing_sl']}")
            updated = True
            break
    if updated:
        save_trades(trades)
        return True
    return False

def manage_trade_position(kite, trade_id, action, lot_size, lots_count):
    trades = load_trades()
    updated = False
    
    for t in trades:
        if str(t['id']) == str(trade_id):
            qty_delta = lots_count * lot_size
            ltp = t.get('current_ltp', 0)
            
            if ltp == 0: # Try to fetch if 0
                try: ltp = kite.quote(f"{t['exchange']}:{t['symbol']}")[f"{t['exchange']}:{t['symbol']}"]['last_price']
                except: pass
            
            if action == 'ADD':
                # Average Entry Calculation
                old_qty = t['quantity']
                old_entry = t['entry_price']
                
                new_total_qty = old_qty + qty_delta
                # Weighted Average
                new_avg_entry = ((old_qty * old_entry) + (qty_delta * ltp)) / new_total_qty
                
                t['quantity'] = new_total_qty
                t['entry_price'] = new_avg_entry
                
                log_event(t, f"Added {qty_delta} Qty ({lots_count} Lots) @ {ltp}. New Avg Entry: {new_avg_entry:.2f}")
                
                if t['mode'] == 'LIVE':
                    try: kite.place_order(tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_BUY,
                        quantity=qty_delta, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                    except Exception as e: log_event(t, f"Broker Fail (Add): {e}")

                updated = True
                
            elif action == 'EXIT':
                if t['quantity'] > qty_delta:
                    t['quantity'] -= qty_delta
                    
                    # Log Profit Booking
                    pnl_booked = (ltp - t['entry_price']) * qty_delta
                    log_event(t, f"Partial Profit: Sold {qty_delta} Qty ({lots_count} Lots) @ {ltp}. Booked P/L: ₹ {pnl_booked:.2f}")
                    
                    if t['mode'] == 'LIVE':
                        try: kite.place_order(tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL,
                            quantity=qty_delta, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                        except Exception as e: log_event(t, f"Broker Fail (Exit): {e}")

                    updated = True
                else:
                    return False # Cannot exit more than held
            break
            
    if updated:
        save_trades(trades)
        return True
    return False

def get_time_str():
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

def log_event(trade, message):
    if 'logs' not in trade: trade['logs'] = []
    trade['logs'].append(f"[{get_time_str()}] {message}")

def move_to_history(trade, final_status, exit_price):
    real_pnl = 0
    if trade['status'] != 'PENDING':
        real_pnl = round((exit_price - trade['entry_price']) * trade['quantity'], 2)

    if trade['status'] == 'PENDING' or (trade.get('order_type') == 'SIMULATION' and "SL" in final_status):
        trade['pnl'] = 0
    else:
        trade['pnl'] = real_pnl
    
    trade['status'] = final_status; trade['exit_price'] = exit_price
    trade['exit_time'] = get_time_str(); trade['exit_type'] = final_status
    
    if "Closed:" not in str(trade['logs']):
         log_event(trade, f"Closed: {final_status} @ {exit_price} | P/L ₹ {real_pnl:.2f}")
    
    try:
        db.session.merge(TradeHistory(id=trade['id'], data=json.dumps(trade)))
        db.session.commit()
    except: db.session.rollback()

def get_exchange(symbol):
    s = symbol.upper()
    if any(x in s for x in ['CRUDEOIL', 'GOLD', 'SILVER', 'COPPER', 'NATURALGAS']): return "MCX"
    if any(x in s for x in ['USDINR', 'EURINR', 'GBPINR', 'JPYINR']): return "CDS"
    if "SENSEX" in s or "BANKEX" in s: return "BFO" if any(char.isdigit() for char in s) else "BSE"
    if symbol.endswith("CE") or symbol.endswith("PE") or "FUT" in symbol: return "NFO"
    return "NSE"

def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points, custom_targets, order_type, limit_price=0):
    trades = load_trades()
    exchange = get_exchange(specific_symbol)
    
    current_ltp = 0.0
    try: current_ltp = kite.quote(f"{exchange}:{specific_symbol}")[f"{exchange}:{specific_symbol}"]["last_price"]
    except: return {"status": "error", "message": "Failed to fetch Live Price"}

    status = "OPEN"; entry_price = current_ltp; trigger_dir = "BELOW"
    if order_type == "LIMIT":
        entry_price = float(limit_price)
        if entry_price <= 0: return {"status": "error", "message": "Invalid Limit Price"}
        status = "PENDING"
        trigger_dir = "ABOVE" if entry_price >= current_ltp else "BELOW"

    if mode == "LIVE" and status == "OPEN":
        try:
            kite.place_order(tradingsymbol=specific_symbol, exchange=exchange, transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=quantity, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
        except Exception as e: return {"status": "error", "message": str(e)}

    targets = custom_targets if len(custom_targets) == 3 else [entry_price + (sl_points * x) for x in [0.5, 1.0, 2.0]]
    logs = [f"[{get_time_str()}] Trade Added. Status: {status}"]

    record = {
        "id": int(time.time()), "entry_time": get_time_str(), "symbol": specific_symbol, "exchange": exchange,
        "mode": mode, "order_type": order_type, "status": status, "entry_price": entry_price, "quantity": quantity,
        "sl": entry_price - sl_points, "targets": targets, "trailing_sl": 0, "targets_hit_indices": [],
        "highest_ltp": entry_price, "made_high": entry_price, "current_ltp": current_ltp, "trigger_dir": trigger_dir, "logs": logs
    }
    trades.append(record)
    save_trades(trades)
    return {"status": "success", "trade": record}

def promote_to_live(kite, trade_id):
    trades = load_trades()
    for t in trades:
        if t['id'] == int(trade_id) and t['mode'] == "PAPER":
            try:
                kite.place_order(tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_BUY,
                    quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                t['mode'] = "LIVE"; t['status'] = "PROMOTED_LIVE"
                log_event(t, "Promoted to LIVE")
                save_trades(trades)
                return True
            except: return False
    return False

def close_trade_manual(kite, trade_id):
    trades = load_trades()
    active_list = []; found = False
    for t in trades:
        if t['id'] == int(trade_id):
            found = True
            if t['status'] == "PENDING":
                move_to_history(t, "CANCELLED_MANUAL", 0)
                continue
            
            exit_p = t.get('current_ltp', 0)
            try: exit_p = kite.quote(f"{t['exchange']}:{t['symbol']}")[f"{t['exchange']}:{t['symbol']}"]['last_price']
            except: pass

            if t['mode'] == "LIVE" and t['status'] != "MONITORING":
                try: kite.place_order(tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL,
                        quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                except: pass
            
            move_to_history(t, "MANUAL_EXIT", exit_p)
        else: active_list.append(t)
            
    if found: save_trades(active_list)
    return found

def inject_simulated_trade(trade_data, is_active):
    trade_data['id'] = int(time.time()); trade_data['mode'] = "PAPER"; trade_data['order_type'] = "SIMULATION"
    if 'exchange' not in trade_data: trade_data['exchange'] = get_exchange(trade_data['symbol'])
    
    if is_active:
        trades = load_trades()
        trades.append(trade_data)
        save_trades(trades)
    else:
        trade_data['pnl'] = 0 if "SL" in trade_data.get('status', '') else round((trade_data.get('made_high', 0) - trade_data['entry_price']) * trade_data['quantity'], 2)
        if not trade_data.get('exit_time'): trade_data['exit_time'] = get_time_str()
        try:
            db.session.merge(TradeHistory(id=trade_data['id'], data=json.dumps(trade_data)))
            db.session.commit()
        except: db.session.rollback()

def update_risk_engine(kite):
    now = datetime.now(IST)
    if now.hour == 15 and now.minute >= 25: # Auto Squareoff
        trades = load_trades()
        if trades:
            for t in trades:
                exit_p = t.get('current_ltp', 0)
                if t['mode'] == "LIVE" and t['status'] != 'PENDING':
                    try: kite.place_order(tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                    except: pass
                move_to_history(t, "AUTO_SQUAREOFF" if t['status']!='PENDING' else "CANCELLED_AUTO", exit_p)
            save_trades([])
        return

    trades = load_trades()
    instruments_to_fetch = set([f"{t['exchange']}:{t['symbol']}" for t in trades])
    if not instruments_to_fetch: return

    try: live_prices = kite.quote(list(instruments_to_fetch))
    except: return

    active_list = []; updated = False
    for t in trades:
        inst_key = f"{t['exchange']}:{t['symbol']}"
        if inst_key not in live_prices:
             active_list.append(t); continue
             
        ltp = live_prices[inst_key]['last_price']; t['current_ltp'] = ltp; updated = True
        
        if t['status'] == "PENDING":
            if (t.get('trigger_dir') == 'BELOW' and ltp <= t['entry_price']) or (t.get('trigger_dir') == 'ABOVE' and ltp >= t['entry_price']):
                t['status'] = "OPEN"; t['highest_ltp'] = t['entry_price']
                log_event(t, f"Order ACTIVATED @ {ltp}")
                if t['mode'] == 'LIVE':
                    try: kite.place_order(tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_BUY, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                    except Exception as e: log_event(t, f"Broker Fail: {e}")
                active_list.append(t)
            else: active_list.append(t)
            continue

        if t['status'] in ['OPEN', 'PROMOTED_LIVE']:
            t['highest_ltp'] = max(t.get('highest_ltp', 0), ltp); t['made_high'] = t['highest_ltp']
            
            # Trailing SL
            if t.get('trailing_sl', 0) > 0:
                new_sl = ltp - t['trailing_sl']
                if new_sl > t['sl']:
                    t['sl'] = new_sl
                    log_event(t, f"Trailing SL Moved to {t['sl']:.2f}")

            # Exit Conditions
            exit_triggered = False; exit_reason = ""
            if ltp <= t['sl']:
                exit_triggered = True; exit_reason = "COST_EXIT" if t['sl'] >= t['entry_price'] else "SL_HIT"
            elif not exit_triggered:
                for i, tgt in enumerate(t['targets']):
                    if i not in t.get('targets_hit_indices', []) and ltp >= tgt:
                        t.setdefault('targets_hit_indices', []).append(i)
                        log_event(t, f"Target {i+1} Hit @ {tgt}")
                        if i == len(t['targets']) - 1:
                            exit_triggered = True; exit_reason = "TARGET_HIT"

            if exit_triggered:
                if t['mode'] == "LIVE":
                    try: kite.place_order(tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                    except: pass
                move_to_history(t, exit_reason, (t['sl'] if exit_reason=="SL_HIT" else t['targets'][-1] if exit_reason=="TARGET_HIT" else ltp))
            else:
                active_list.append(t)
    
    if updated: save_trades(active_list)
