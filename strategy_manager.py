import json
import time
from datetime import datetime, timedelta
import pandas as pd
import pytz
from database import db, ActiveTrade, TradeHistory

# Global IST Timezone
IST = pytz.timezone('Asia/Kolkata')

def load_trades():
    try:
        trades = []
        rows = ActiveTrade.query.all()
        for r in rows:
            trades.append(json.loads(r.data))
        return trades
    except Exception as e:
        print(f"Load Trades Error: {e}")
        return []

def save_trades(trades):
    try:
        db.session.query(ActiveTrade).delete()
        for t in trades:
            db.session.add(ActiveTrade(data=json.dumps(t)))
        db.session.commit()
    except Exception as e:
        print(f"Save Trades Error: {e}")
        db.session.rollback()

def load_history():
    try:
        rows = TradeHistory.query.order_by(TradeHistory.id.desc()).all()
        return [json.loads(r.data) for r in rows]
    except Exception as e:
        print(f"Load History Error: {e}")
        return []

def save_history_file(history):
    pass

def delete_trade(trade_id):
    try:
        TradeHistory.query.filter_by(id=int(trade_id)).delete()
        db.session.commit()
        return True
    except Exception as e:
        print(f"Delete Error: {e}")
        db.session.rollback()
        return False

def update_trade_protection(trade_id, sl, targets, trailing_sl=0):
    trades = load_trades()
    updated = False
    for t in trades:
        if str(t['id']) == str(trade_id):
            old_sl = t['sl']
            t['sl'] = float(sl)
            t['targets'] = [float(x) for x in targets]
            t['trailing_sl'] = float(trailing_sl) if trailing_sl else 0
            
            msg = f"Manual Update: SL {old_sl} -> {t['sl']}, Targets Updated"
            if t['trailing_sl'] > 0:
                msg += f", Trailing SL set to {t['trailing_sl']} pts"
            
            log_event(t, msg)
            updated = True
            break
    
    if updated:
        save_trades(trades)
        return True
    return False

def get_time_str():
    try:
        return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    except:
        return pd.Timestamp.now('Asia/Kolkata').strftime("%Y-%m-%d %H:%M:%S")

def log_event(trade, message):
    if 'logs' not in trade:
        trade['logs'] = []
    trade['logs'].append(f"[{get_time_str()}] {message}")

def move_to_history(trade, final_status, exit_price):
    if trade['status'] == 'PENDING':
        trade['pnl'] = 0
    else:
        # Real PnL Calculation
        trade['pnl'] = round((exit_price - trade['entry_price']) * trade['quantity'], 2)
    
    trade['status'] = final_status
    trade['exit_price'] = exit_price
    trade['exit_time'] = get_time_str()
    
    if "Closed:" not in str(trade['logs']):
         log_event(trade, f"Closed: {final_status} @ {exit_price}")
    
    try:
        hist = TradeHistory(id=trade['id'], data=json.dumps(trade))
        db.session.merge(hist)
        db.session.commit()
    except Exception as e:
        print(f"History Save Error: {e}")
        db.session.rollback()

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
        "trailing_sl": 0, # Default 0
        "targets_hit_indices": [],
        "highest_ltp": entry_price, 
        "made_high": entry_price,
        "high_locked": False, 
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

            exit_p = t.get('current_ltp', 0)
            try:
                q = kite.quote(f"{t['exchange']}:{t['symbol']}")
                exit_p = q[f"{t['exchange']}:{t['symbol']}"]['last_price']
            except Exception as e:
                print(f"Manual Exit LTP Fetch Error: {e}")

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
            
            move_to_history(t, "MANUAL_EXIT", exit_p)
            
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
        if trade_data.get('status') == 'PENDING':
             trade_data['pnl'] = 0
             trade_data['exit_price'] = 0
        else:
             trade_data['pnl'] = round((trade_data.get('made_high', 0) - trade_data['entry_price']) * trade_data['quantity'], 2)
             trade_data['exit_price'] = trade_data.get('made_high', 0)
        
        if not trade_data.get('exit_time'):
             trade_data['exit_time'] = get_time_str()

        try:
            hist = TradeHistory(id=trade_data['id'], data=json.dumps(trade_data))
            db.session.merge(hist)
            db.session.commit()
        except Exception as e:
            print(f"Sim History Save Error: {e}")
            db.session.rollback()

def process_eod_data(kite):
    """
    3:35 PM Trigger: 
    1. Checks closed trades for the day.
    2. Updates 'Made High' using Historical Data API for ALL trades.
    3. For SIMULATOR: Updates P&L based on High (Potential).
    4. For LIVE/PAPER: Updates Made High but PRESERVES Real P&L.
    """
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    history = load_history()
    
    updated_count = 0
    
    for trade in history:
        # Check if trade is from today and not already processed for EOD high
        if trade.get('exit_time', '').startswith(today_str) and not trade.get('eod_scan_done', False):
            
            try:
                symbol = trade['symbol']
                exchange = trade['exchange']
                
                # Fetch Instrument Token
                quote_data = kite.quote(f"{exchange}:{symbol}")
                token = quote_data[f"{exchange}:{symbol}"]['instrument_token']
                
                # Define Time Range (Entry Time to Market Close/Exit)
                entry_dt = datetime.strptime(trade['entry_time'], "%Y-%m-%d %H:%M:%S")
                end_dt = datetime.now(IST)
                
                # Fetch Minute Candles
                candles = kite.historical_data(token, entry_dt, end_dt, "minute")
                
                if candles:
                    # Calculate Max High during the period
                    max_high = max([c['high'] for c in candles])
                    
                    trade['made_high'] = max_high
                    trade['highest_ltp'] = max_high # Sync both fields
                    trade['eod_scan_done'] = True
                    
                    log_event(trade, f"EOD Scan: Made High Updated to {max_high}")
                    
                    if trade.get('order_type') == 'SIMULATION':
                        # For Simulator: Show Potential P&L based on High
                        trade['exit_price'] = max_high
                        trade['pnl'] = round((max_high - trade['entry_price']) * trade['quantity'], 2)
                        log_event(trade, f"EOD Scan: SIM PnL Updated to {trade['pnl']} (Based on Made High)")
                    else:
                        # For Live/Paper: Show Real P&L (Recalculate to be sure)
                        real_exit = trade.get('exit_price', 0)
                        if real_exit > 0:
                            trade['pnl'] = round((real_exit - trade['entry_price']) * trade['quantity'], 2)
                        log_event(trade, f"EOD Scan: Real PnL Confirmed at {trade['pnl']} (Made High was {max_high})")
                    
                    # Save back to DB
                    db.session.merge(TradeHistory(id=trade['id'], data=json.dumps(trade)))
                    updated_count += 1
            
            except Exception as e:
                print(f"EOD Scan Error for {trade['symbol']}: {e}")
                
    if updated_count > 0:
        db.session.commit()
        print(f"EOD Scan Completed. Updated {updated_count} trades.")

def update_risk_engine(kite):
    now = datetime.now(IST)
    
    # --- 1. Auto Trigger: Force Exit at 3:25 PM ---
    if now.hour == 15 and now.minute >= 25:
        trades = load_trades()
        if trades:
            for t in trades:
                exit_p = t.get('current_ltp', 0)
                
                if t['status'] != 'PENDING':
                    try:
                        q = kite.quote(f"{t['exchange']}:{t['symbol']}")
                        exit_p = q[f"{t['exchange']}:{t['symbol']}"]['last_price']
                    except:
                        pass
                
                if t['mode'] == "LIVE" and t['status'] != 'PENDING':
                    try:
                        kite.place_order(
                            tradingsymbol=t['symbol'],
                            exchange=t['exchange'],
                            transaction_type=kite.TRANSACTION_TYPE_SELL,
                            quantity=t['quantity'],
                            order_type=kite.ORDER_TYPE_MARKET,
                            product=kite.PRODUCT_MIS
                        )
                    except Exception as e:
                        log_event(t, f"Auto-Exit Broker Error: {e}")

                reason = "AUTO_SQUAREOFF"
                if t['status'] == 'PENDING': reason = "CANCELLED_AUTO"
                
                move_to_history(t, reason, exit_p)
            
            # Clear Active Trades
            save_trades([])
            return # Stop processing further

    # --- 2. Auto Trigger: Check Made High at 3:35 PM ---
    if now.hour == 15 and now.minute >= 35:
        process_eod_data(kite)
        return

    # --- 3. Normal Risk Management (Before 3:25 PM) ---
    trades = load_trades()
    active_list = []
    updated = False
    
    for t in trades:
        try:
            ltp = kite.quote(f"{t['exchange']}:{t['symbol']}")[f"{t['exchange']}:{t['symbol']}"]["last_price"]
            t['current_ltp'] = ltp
            updated = True
            
            if t['status'] != "PENDING":
                if 'highest_ltp' not in t: t['highest_ltp'] = t['entry_price']
                if ltp > t['highest_ltp']:
                    t['highest_ltp'] = ltp
            
        except:
            active_list.append(t)
            continue

        if t['status'] == "PENDING":
            should_activate = False
            trigger_dir = t.get('trigger_dir', 'BELOW')
            
            if trigger_dir == 'BELOW' and ltp <= t['entry_price']:
                should_activate = True
            elif trigger_dir == 'ABOVE' and ltp >= t['entry_price']:
                should_activate = True

            if should_activate:
                t['status'] = "OPEN"
                t['highest_ltp'] = t['entry_price'] 
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

        if t['status'] in ['OPEN', 'PROMOTED_LIVE']:
            exit_triggered = False
            exit_reason = ""
            exit_p = ltp
            
            # --- Trailing SL Logic ---
            trail_pts = t.get('trailing_sl', 0)
            if trail_pts > 0:
                # Calculate what SL should be based on current LTP
                new_calculated_sl = ltp - trail_pts
                
                # Only move SL UP
                if new_calculated_sl > t['sl']:
                    old_sl_val = t['sl']
                    t['sl'] = new_calculated_sl
                    log_event(t, f"Trailing SL Moved: {old_sl_val:.2f} -> {t['sl']:.2f} (LTP: {ltp})")

            # --- Stop Loss Check ---
            if ltp <= t['sl']:
                exit_triggered = True
                exit_p = t['sl']
                if t['sl'] >= t['entry_price']:
                    exit_reason = "COST_EXIT"
                    log_event(t, f"Price returned to Entry/Cost @ {ltp}. Safe Exit triggered.")
                else:
                    exit_reason = "SL_HIT"
                    log_event(t, f"SL Hit @ {ltp}")

            # --- Target Check ---
            if not exit_triggered:
                if 'targets_hit_indices' not in t: t['targets_hit_indices'] = []
                
                for i, tgt in enumerate(t['targets']):
                    if i not in t['targets_hit_indices'] and ltp >= tgt:
                        t['targets_hit_indices'].append(i)
                        log_event(t, f"Target {i+1} Hit @ {tgt}")
                        
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
                    except Exception as e:
                         log_event(t, f"Broker Exit Failed: {str(e)}")
                
                t['highest_ltp'] = max(t.get('highest_ltp', 0), exit_p) 
                t['made_high'] = t['highest_ltp']
                move_to_history(t, exit_reason, exit_p)
            else:
                active_list.append(t)
                
    if updated:
        save_trades(active_list)
