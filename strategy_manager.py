import json
import time
from datetime import datetime, timedelta
import pandas as pd
import pytz
from database import db, ActiveTrade, TradeHistory
import smart_trader 

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

def update_trade_protection(trade_id, sl, targets, trailing_sl=0, entry_price=None, target_controls=None, sl_to_entry=0, exit_multiplier=1):
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
            t['trailing_sl'] = float(trailing_sl) if trailing_sl else 0
            t['sl_to_entry'] = int(sl_to_entry)
            t['exit_multiplier'] = int(exit_multiplier) # SAVE EXIT MULTIPLIER
            
            # Handle Exit Multiplier Logic (Recalculate Targets & Controls)
            if exit_multiplier > 1:
                eff_entry = t['entry_price']
                eff_sl_points = eff_entry - float(sl)
                
                # Determine Goal from passed targets (user inputs) or default
                valid_custom = [x for x in targets if x > 0]
                if valid_custom: final_goal = max(valid_custom)
                else: final_goal = eff_entry + (eff_sl_points * 2)
                
                dist = final_goal - eff_entry
                new_targets = []
                new_controls = []
                
                lot_size = t.get('lot_size')
                if not lot_size:
                    lot_size = smart_trader.get_lot_size(t['symbol'])
                    
                total_lots = t['quantity'] // lot_size
                base_lots = total_lots // exit_multiplier
                remainder = total_lots % exit_multiplier
                
                for i in range(1, exit_multiplier + 1):
                    fraction = i / exit_multiplier
                    t_price = eff_entry + (dist * fraction)
                    new_targets.append(round(t_price, 2))
                    
                    lots_here = base_lots
                    if i == exit_multiplier: lots_here += remainder
                    new_controls.append({'enabled': True, 'lots': int(lots_here)})
                
                while len(new_targets) < 3:
                    new_targets.append(0)
                    new_controls.append({'enabled': False, 'lots': 0})
                
                t['targets'] = new_targets
                t['target_controls'] = new_controls
            else:
                t['targets'] = [float(x) for x in targets]
                if target_controls:
                    t['target_controls'] = target_controls
            
            # Detailed Logging for Targets
            tgt_log = []
            controls = t.get('target_controls', [{'enabled':True, 'lots':0}]*3)
            for i, p in enumerate(t['targets']):
                c = controls[i] if i < len(controls) else {'enabled':True, 'lots':0}
                status = "ON" if c['enabled'] else "OFF"
                tgt_log.append(f"{p}({status}, {c['lots']}L)")
            
            # Label trail mode for logs
            trail_map = {0:"Unlimited", 1:"To Entry", 2:"To T1", 3:"To T2", 4:"To T3"}
            trail_mode = trail_map.get(t['sl_to_entry'], "Unlimited")
            
            mult_msg = f" | Multiplier: {exit_multiplier}x" if exit_multiplier > 1 else ""
            log_event(t, f"Manual Update: SL {old_sl} -> {t['sl']}{entry_msg}. Targets: {', '.join(tgt_log)}. Trail: {t['trailing_sl']} ({trail_mode}){mult_msg}")
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
    was_active = trade['status'] != 'PENDING'

    if was_active:
        real_pnl = round((exit_price - trade['entry_price']) * trade['quantity'], 2)

    if not was_active:
        trade['pnl'] = 0
    else:
        trade['pnl'] = real_pnl
    
    trade['status'] = final_status; trade['exit_price'] = exit_price
    trade['exit_time'] = get_time_str(); trade['exit_type'] = final_status
    
    # 1. Log "Closed" FIRST
    if "Closed:" not in str(trade['logs']):
         log_event(trade, f"Closed: {final_status} @ {exit_price} | P/L ₹ {real_pnl:.2f}")
    
    # 2. Log "Info: Made High" LAST
    if was_active:
        # Use whatever high was recorded during the trade. 
        # We do NOT force update to exit_price here (as per instruction).
        # Post-close monitoring in update_risk_engine will catch higher prices.
        made_high = trade.get('made_high', trade['entry_price'])
        
        trade['made_high'] = made_high
        max_pnl = (made_high - trade['entry_price']) * trade['quantity']
        
        log_event(trade, f"Info: Made High: {made_high} | Max P/L ₹ {max_pnl:.2f}")
    
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

def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points, custom_targets, order_type, limit_price=0, target_controls=None, trailing_sl=0, sl_to_entry=0, exit_multiplayer=1):
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

    targets = custom_targets if len(custom_targets) == 3 and custom_targets[0] > 0 else [entry_price + (sl_points * x) for x in [0.5, 1.0, 2.0]]
    
    if not target_controls:
        target_controls = [
            {'enabled': True, 'lots': 0}, 
            {'enabled': True, 'lots': 0}, 
            {'enabled': True, 'lots': 1000}
        ]
    
    lot_size = smart_trader.get_lot_size(specific_symbol)
    
    # --- EXIT MULTIPLAYER LOGIC ---
    if exit_multiplayer > 1:
        # 1. Determine Final Goal Price (Max of set targets or default to T3 default)
        final_goal = 0
        valid_custom = [x for x in custom_targets if x > 0]
        if valid_custom:
             final_goal = max(valid_custom)
        else:
             final_goal = entry_price + (sl_points * 2) # Default Fallback

        # 2. Calculate Steps
        dist = final_goal - entry_price
        
        new_targets = []
        new_controls = []
        
        total_lots = quantity // lot_size
        base_lots = total_lots // exit_multiplayer
        remainder = total_lots % exit_multiplayer
        
        for i in range(1, exit_multiplayer + 1):
            fraction = i / exit_multiplayer
            t_price = entry_price + (dist * fraction)
            new_targets.append(round(t_price, 2))
            
            # Distribute lots
            lots_here = base_lots
            if i == exit_multiplayer:
                lots_here += remainder
            
            new_controls.append({'enabled': True, 'lots': int(lots_here)})
        
        # Pad with dummies if needed
        while len(new_targets) < 3:
            new_targets.append(0)
            new_controls.append({'enabled': False, 'lots': 0})
            
        targets = new_targets
        target_controls = new_controls
    # ------------------------------

    logs = [f"[{get_time_str()}] Trade Added. Status: {status}"]

    record = {
        "id": int(time.time()), "entry_time": get_time_str(), "symbol": specific_symbol, "exchange": exchange,
        "mode": mode, "order_type": order_type, "status": status, "entry_price": entry_price, "quantity": quantity,
        "sl": entry_price - sl_points, "targets": targets, "target_controls": target_controls,
        "lot_size": lot_size, "trailing_sl": float(trailing_sl), "sl_to_entry": int(sl_to_entry),
        "exit_multiplier": int(exit_multiplayer), # SAVE EXIT MULTIPLIER to Record
        "targets_hit_indices": [],
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

    active_trades = load_trades()
    
    # --- NEW: Monitor History for Potential Profit Updates ---
    history_trades = load_history()
    today_str = now.strftime("%Y-%m-%d")
    monitoring_history = [t for t in history_trades if t.get('exit_time', '').startswith(today_str)]
    # ---------------------------------------------------------

    instruments_to_fetch = set([f"{t['exchange']}:{t['symbol']}" for t in active_trades])
    # Add today's closed trades to fetch list
    for t in monitoring_history:
        instruments_to_fetch.add(f"{t['exchange']}:{t['symbol']}")

    if not instruments_to_fetch: return

    try: live_prices = kite.quote(list(instruments_to_fetch))
    except: return

    # 1. Process Active Trades
    active_list = []; updated_active = False
    for t in active_trades:
        if t.get('lot_size', 0) == 0:
            ls = smart_trader.get_lot_size(t['symbol'])
            if ls > 0:
                t['lot_size'] = ls
                updated_active = True
                
        inst_key = f"{t['exchange']}:{t['symbol']}"
        if inst_key not in live_prices:
             active_list.append(t); continue
             
        ltp = live_prices[inst_key]['last_price']; t['current_ltp'] = ltp; updated_active = True
        
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
                
                # Logic Update: Integer Trail Modes
                limit_mode = int(t.get('sl_to_entry', 0))
                limit_price = float('inf')
                
                if limit_mode == 1: limit_price = t['entry_price']
                elif limit_mode == 2 and len(t['targets']) > 0: limit_price = t['targets'][0]
                elif limit_mode == 3 and len(t['targets']) > 1: limit_price = t['targets'][1]
                elif limit_mode == 4 and len(t['targets']) > 2: limit_price = t['targets'][2]
                
                if limit_mode > 0:
                    new_sl = min(new_sl, limit_price)
                
                if new_sl > t['sl']:
                    t['sl'] = new_sl
                    log_event(t, f"Trailing SL Moved to {t['sl']:.2f}")

            # Exit Conditions
            exit_triggered = False; exit_reason = ""
            
            if ltp <= t['sl']:
                exit_triggered = True; exit_reason = "COST_EXIT" if t['sl'] >= t['entry_price'] else "SL_HIT"
            elif not exit_triggered:
                controls = t.get('target_controls', [{'enabled':True, 'lots':0}, {'enabled':True, 'lots':0}, {'enabled':True, 'lots':1000}])
                for i, tgt in enumerate(t['targets']):
                    if i not in t.get('targets_hit_indices', []) and ltp >= tgt:
                        t.setdefault('targets_hit_indices', []).append(i)
                        conf = controls[i]
                        if not conf['enabled']:
                             log_event(t, f"Crossed T{i+1} @ {tgt} (Target Disabled - No Action)")
                             continue
                        
                        lot_size = t.get('lot_size', 1)
                        exit_lots = conf.get('lots', 0)
                        qty_to_exit = exit_lots * lot_size
                        
                        if qty_to_exit >= t['quantity']:
                             exit_triggered = True; exit_reason = "TARGET_HIT"
                             break
                        elif qty_to_exit > 0:
                             t['quantity'] -= qty_to_exit
                             pnl_booked = (tgt - t['entry_price']) * qty_to_exit
                             log_event(t, f"Target {i+1} Hit @ {tgt}. Auto-Exited {qty_to_exit} Qty. P/L Booked: {pnl_booked:.2f}")
                             if t['mode'] == 'LIVE':
                                try: kite.place_order(tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=qty_to_exit, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                                except: pass
                        else:
                             log_event(t, f"Target {i+1} Hit @ {tgt} (No Auto-Exit Configured)")

            if exit_triggered:
                if t['mode'] == "LIVE":
                    try: kite.place_order(tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                    except: pass
                move_to_history(t, exit_reason, (t['sl'] if exit_reason=="SL_HIT" else t['targets'][-1] if exit_reason=="TARGET_HIT" else ltp))
            else:
                active_list.append(t)
    
    if updated_active: save_trades(active_list)

    # 2. Process Closed Trades (Post-Close Monitoring)
    updated_hist = False
    for t in monitoring_history:
        inst_key = f"{t['exchange']}:{t['symbol']}"
        if inst_key in live_prices:
            ltp = live_prices[inst_key]['last_price']
            
            # Update Made High if Current LTP is higher
            current_high = t.get('made_high', 0)
            if ltp > current_high:
                t['made_high'] = ltp
                # We update DB silently so UI 'Potential Profit' increases
                try:
                    db.session.merge(TradeHistory(id=t['id'], data=json.dumps(t)))
                    updated_hist = True
                except: pass
    
    if updated_hist:
        try: db.session.commit()
        except: db.session.rollback()

def square_off_all(kite):
    """
    Panic Button Logic: Closes ALL active trades immediately.
    """
    trades = load_trades()
    if not trades: return False
    
    # 1. Fetch fresh prices for accurate logging
    try:
        symbols = [f"{t['exchange']}:{t['symbol']}" for t in trades]
        live_data = kite.quote(symbols)
    except:
        live_data = {}

    for t in trades:
        # Determine exit price
        exit_p = t.get('current_ltp', 0)
        inst = f"{t['exchange']}:{t['symbol']}"
        if inst in live_data:
            exit_p = live_data[inst]['last_price']
            
        # Execute Sell Order for LIVE trades
        if t['mode'] == "LIVE" and t['status'] != "PENDING":
            try:
                kite.place_order(tradingsymbol=t['symbol'], exchange=t['exchange'], 
                                 transaction_type=kite.TRANSACTION_TYPE_SELL, 
                                 quantity=t['quantity'], 
                                 order_type=kite.ORDER_TYPE_MARKET, 
                                 product=kite.PRODUCT_MIS)
                log_event(t, "⚠️ PANIC EXIT TRIGGERED: Order Placed.")
            except Exception as e:
                log_event(t, f"❌ Panic Exit Broker Failed: {e}")
        
        # Determine Status
        final_status = "PANIC_EXIT"
        if t['status'] == "PENDING": final_status = "PANIC_CANCEL"
        
        move_to_history(t, final_status, exit_p)
    
    # Clear Active Trades
    save_trades([])
    return True
