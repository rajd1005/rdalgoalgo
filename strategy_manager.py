import json
import time
import threading
from datetime import datetime
import pytz
from database import db, ActiveTrade, TradeHistory
import smart_trader

IST = pytz.timezone('Asia/Kolkata')

# --- THREAD SAFETY & MONITORING ---
trade_lock = threading.Lock()
monitor_active = False
monitor_thread = None

def get_time_str():
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

# --- DATA ACCESS HELPERS ---

def load_trades():
    """Fetches trades from DB and converts to Dict for UI"""
    try:
        # We read from DB, no lock needed for simple reading
        trades_objs = ActiveTrade.query.all()
        return [t.to_dict() for t in trades_objs]
    except Exception as e:
        print(f"Load Trades Error: {e}")
        return []

def log_event(trade_obj, message):
    """Appends log to the JSON column safely"""
    try:
        current_logs = json.loads(trade_obj.logs_json)
        current_logs.append(f"[{get_time_str()}] {message}")
        trade_obj.logs_json = json.dumps(current_logs)
    except Exception as e:
        print(f"Logging Error: {e}")

# --- MARKET MONITOR (BACKGROUND THREAD) ---

def start_monitor(kite, app):
    global monitor_active, monitor_thread
    if monitor_active: return
    
    monitor_active = True
    monitor_thread = threading.Thread(target=run_market_monitor, args=(kite, app), daemon=True)
    monitor_thread.start()
    print("🚀 Market Monitor Thread Started")

def stop_monitor():
    global monitor_active
    monitor_active = False
    print("🛑 Market Monitor Stopping...")

def run_market_monitor(kite, app):
    """
    Dedicated thread to fetch prices and update risk.
    Runs every ~1 second to prevent API Rate Limits.
    """
    global monitor_active
    
    print("✅ Risk Engine Active")
    
    while monitor_active:
        try:
            with app.app_context():
                update_risk_engine(kite)
        except Exception as e:
            print(f"❌ Monitor Loop Error: {e}")
        
        time.sleep(1) # Rate Limit Control (1 request / sec approx)

def update_risk_engine(kite):
    """
    Fetches LTP and updates Stoploss/Targets.
    Uses locking only when writing to DB.
    """
    now = datetime.now(IST)
    
    # 1. Auto Squareoff Time
    if now.hour == 15 and now.minute >= 25:
        with trade_lock:
            trades = ActiveTrade.query.all()
            for t in trades:
                if t.mode == "LIVE" and t.status != 'PENDING':
                    try: kite.place_order(tradingsymbol=t.symbol, exchange=t.exchange, transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t.quantity, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                    except: pass
                move_to_history_db(t, "AUTO_SQUAREOFF" if t.status!='PENDING' else "CANCELLED_AUTO", t.current_ltp)
            db.session.commit()
        return

    # 2. Fetch Active Trades
    trades = ActiveTrade.query.all()
    if not trades: return

    # 3. Fetch History for Potential Profit Tracking (Today only)
    today_str = now.strftime("%Y-%m-%d")
    # Note: History is JSON blob, so we fetch all and filter in python (inefficient but safe for small history)
    hist_records = TradeHistory.query.all() 
    monitoring_history = []
    for h in hist_records:
        h_data = json.loads(h.data)
        if h_data.get('exit_time', '').startswith(today_str):
             monitoring_history.append((h, h_data))

    # 4. Prepare Instruments to Quote
    instruments_to_fetch = set([f"{t.exchange}:{t.symbol}" for t in trades])
    for _, h_data in monitoring_history:
        instruments_to_fetch.add(f"{h_data['exchange']}:{h_data['symbol']}")

    if not instruments_to_fetch: return

    try: 
        live_prices = kite.quote(list(instruments_to_fetch))
    except Exception as e: 
        print(f"Quote Error: {e}")
        return

    # 5. Process Updates (With Lock)
    with trade_lock:
        updated = False
        
        # A. Update Active Trades
        for t in trades:
            inst_key = f"{t.exchange}:{t.symbol}"
            if inst_key not in live_prices: continue
            
            ltp = live_prices[inst_key]['last_price']
            t.current_ltp = ltp
            updated = True
            
            # PENDING ORDER LOGIC
            if t.status == "PENDING":
                if (t.trigger_dir == 'BELOW' and ltp <= t.entry_price) or (t.trigger_dir == 'ABOVE' and ltp >= t.entry_price):
                    t.status = "OPEN"
                    t.highest_ltp = t.entry_price
                    log_event(t, f"Order ACTIVATED @ {ltp}")
                    if t.mode == 'LIVE':
                        try: kite.place_order(tradingsymbol=t.symbol, exchange=t.exchange, transaction_type=kite.TRANSACTION_TYPE_BUY, quantity=t.quantity, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                        except Exception as e: log_event(t, f"Broker Fail: {e}")
                continue

            # ACTIVE TRADE LOGIC
            if t.status in ['OPEN', 'PROMOTED_LIVE']:
                t.highest_ltp = max(t.highest_ltp, ltp)
                t.made_high = t.highest_ltp
                
                # Deserialization for logic
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
                    elif limit_mode == 3 and len(targets) > 1: limit_price = targets[1]
                    elif limit_mode == 4 and len(targets) > 2: limit_price = targets[2]
                    
                    if limit_mode > 0: new_sl = min(new_sl, limit_price)
                    
                    if new_sl > t.sl:
                        t.sl = new_sl
                        log_event(t, f"Trailing SL Moved to {t.sl:.2f}")

                # Exit Logic
                exit_triggered = False; exit_reason = ""
                
                if ltp <= t.sl:
                    exit_triggered = True
                    exit_reason = "COST_EXIT" if t.sl >= t.entry_price else "SL_HIT"
                elif not exit_triggered:
                    # Check Targets
                    for i, tgt in enumerate(targets):
                        if i not in hit_indices and ltp >= tgt:
                            hit_indices.append(i)
                            t.targets_hit_indices_json = json.dumps(hit_indices)
                            
                            conf = controls[i] if i < len(controls) else {'enabled':True, 'lots':0}
                            if not conf['enabled']:
                                log_event(t, f"Crossed T{i+1} @ {tgt} (Target Disabled)")
                                continue
                            
                            exit_lots = conf.get('lots', 0)
                            qty_to_exit = exit_lots * t.lot_size
                            
                            if qty_to_exit >= t.quantity:
                                exit_triggered = True; exit_reason = "TARGET_HIT"
                                break
                            elif qty_to_exit > 0:
                                t.quantity -= qty_to_exit
                                pnl_booked = (tgt - t.entry_price) * qty_to_exit
                                log_event(t, f"Target {i+1} Hit @ {tgt}. Auto-Exited {qty_to_exit} Qty. P/L: {pnl_booked:.2f}")
                                if t.mode == 'LIVE':
                                    try: kite.place_order(tradingsymbol=t.symbol, exchange=t.exchange, transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=qty_to_exit, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                                    except: pass
                            else:
                                log_event(t, f"Target {i+1} Hit @ {tgt} (No Auto-Exit)")

                if exit_triggered:
                    if t.mode == "LIVE":
                        try: kite.place_order(tradingsymbol=t.symbol, exchange=t.exchange, transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t.quantity, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                        except: pass
                    move_to_history_db(t, exit_reason, (t.sl if exit_reason=="SL_HIT" else targets[-1] if exit_reason=="TARGET_HIT" else ltp))

        # B. Update History (Potential Profit)
        for h_obj, h_dict in monitoring_history:
            inst_key = f"{h_dict['exchange']}:{h_dict['symbol']}"
            if inst_key in live_prices:
                ltp = live_prices[inst_key]['last_price']
                current_high = h_dict.get('made_high', 0)
                if ltp > current_high:
                    h_dict['made_high'] = ltp
                    h_obj.data = json.dumps(h_dict)
                    updated = True

        if updated:
            db.session.commit()

# --- TRADE ACTIONS ---

def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points, custom_targets, order_type, limit_price=0, target_controls=None, trailing_sl=0, sl_to_entry=0, exit_multiplayer=1):
    
    exchange = smart_trader.get_exchange(specific_symbol)
    
    # 1. Get Live Price
    current_ltp = 0.0
    try: current_ltp = kite.quote(f"{exchange}:{specific_symbol}")[f"{exchange}:{specific_symbol}"]["last_price"]
    except: return {"status": "error", "message": "Failed to fetch Live Price"}

    # 2. Setup Trade Data
    status = "OPEN"; entry_price = current_ltp; trigger_dir = "BELOW"
    if order_type == "LIMIT":
        entry_price = float(limit_price)
        if entry_price <= 0: return {"status": "error", "message": "Invalid Limit Price"}
        status = "PENDING"
        trigger_dir = "ABOVE" if entry_price >= current_ltp else "BELOW"

    # 3. Calculate Targets (Exit Multiplier Logic)
    lot_size = smart_trader.get_lot_size(specific_symbol)
    
    targets = custom_targets
    if exit_multiplayer > 1:
        # Determine Final Goal
        valid_custom = [x for x in custom_targets if x > 0]
        final_goal = max(valid_custom) if valid_custom else entry_price + (sl_points * 2)

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
            
            lots_here = base_lots
            if i == exit_multiplayer: lots_here += remainder
            
            new_controls.append({'enabled': True, 'lots': int(lots_here)})
        
        while len(new_targets) < 3:
            new_targets.append(0); new_controls.append({'enabled': False, 'lots': 0})
            
        targets = new_targets
        target_controls = new_controls

    if not target_controls:
        target_controls = [{'enabled': True, 'lots': 0}, {'enabled': True, 'lots': 0}, {'enabled': True, 'lots': 1000}]

    # 4. Place Broker Order (If LIVE)
    if mode == "LIVE" and status == "OPEN":
        try:
            kite.place_order(tradingsymbol=specific_symbol, exchange=exchange, transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=quantity, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
        except Exception as e: return {"status": "error", "message": str(e)}

    # 5. Save to DB (Atomic)
    with trade_lock:
        try:
            new_trade = ActiveTrade(
                trade_ref=str(int(time.time())),
                symbol=specific_symbol,
                exchange=exchange,
                mode=mode,
                status=status,
                order_type=order_type,
                entry_price=entry_price,
                quantity=quantity,
                lot_size=lot_size,
                current_ltp=current_ltp,
                highest_ltp=entry_price,
                made_high=entry_price,
                sl=entry_price - sl_points,
                trailing_sl=float(trailing_sl),
                sl_to_entry=int(sl_to_entry),
                exit_multiplier=int(exit_multiplayer),
                targets_json=json.dumps(targets),
                target_controls_json=json.dumps(target_controls),
                trigger_dir=trigger_dir,
                entry_time=get_time_str(),
                logs_json=json.dumps([f"[{get_time_str()}] Trade Added. Status: {status}"])
            )
            db.session.add(new_trade)
            db.session.commit()
            return {"status": "success", "trade": new_trade.to_dict()}
        except Exception as e:
            db.session.rollback()
            return {"status": "error", "message": str(e)}

def update_trade_protection(trade_ref, sl, targets, trailing_sl=0, entry_price=None, target_controls=None, sl_to_entry=0, exit_multiplier=1):
    with trade_lock:
        trade = ActiveTrade.query.filter_by(trade_ref=str(trade_ref)).first()
        if not trade: return False
        
        # Log old values
        old_sl = trade.sl
        entry_msg = ""
        
        if entry_price is not None:
            new_entry = float(entry_price)
            if new_entry != trade.entry_price:
                entry_msg = f" | Entry {trade.entry_price} -> {new_entry}"
                trade.entry_price = new_entry
        
        trade.sl = float(sl)
        trade.trailing_sl = float(trailing_sl) if trailing_sl else 0
        trade.sl_to_entry = int(sl_to_entry)
        trade.exit_multiplier = int(exit_multiplier)

        # Recalculate Logic if Exit Multiplier Changed
        if exit_multiplier > 1:
            eff_entry = trade.entry_price
            eff_sl_points = eff_entry - float(sl)
            
            valid_custom = [x for x in targets if x > 0]
            final_goal = max(valid_custom) if valid_custom else eff_entry + (eff_sl_points * 2)
            
            dist = final_goal - eff_entry
            new_targets = []
            new_controls = []
            
            total_lots = trade.quantity // trade.lot_size
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
                new_targets.append(0); new_controls.append({'enabled': False, 'lots': 0})
            
            trade.targets_json = json.dumps(new_targets)
            trade.target_controls_json = json.dumps(new_controls)
        else:
            trade.targets_json = json.dumps([float(x) for x in targets])
            if target_controls:
                trade.target_controls_json = json.dumps(target_controls)

        log_event(trade, f"Manual Update: SL {old_sl} -> {trade.sl}{entry_msg}. Multiplier: {exit_multiplier}x")
        db.session.commit()
        return True

def manage_trade_position(kite, trade_ref, action, lot_size, lots_count):
    with trade_lock:
        trade = ActiveTrade.query.filter_by(trade_ref=str(trade_ref)).first()
        if not trade: return False
        
        qty_delta = lots_count * lot_size
        ltp = trade.current_ltp
        
        if ltp == 0:
            try: ltp = kite.quote(f"{trade.exchange}:{trade.symbol}")[f"{trade.exchange}:{trade.symbol}"]['last_price']
            except: pass

        if action == 'ADD':
            old_qty = trade.quantity
            old_entry = trade.entry_price
            
            new_total_qty = old_qty + qty_delta
            new_avg_entry = ((old_qty * old_entry) + (qty_delta * ltp)) / new_total_qty
            
            trade.quantity = new_total_qty
            trade.entry_price = new_avg_entry
            
            log_event(trade, f"Added {qty_delta} Qty ({lots_count} Lots) @ {ltp}. New Avg Entry: {new_avg_entry:.2f}")
            
            if trade.mode == 'LIVE':
                try: kite.place_order(tradingsymbol=trade.symbol, exchange=trade.exchange, transaction_type=kite.TRANSACTION_TYPE_BUY,
                    quantity=qty_delta, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                except Exception as e: log_event(trade, f"Broker Fail (Add): {e}")

        elif action == 'EXIT':
            if trade.quantity > qty_delta:
                trade.quantity -= qty_delta
                pnl_booked = (ltp - trade.entry_price) * qty_delta
                log_event(trade, f"Partial Profit: Sold {qty_delta} Qty. Booked P/L: ₹ {pnl_booked:.2f}")
                
                if trade.mode == 'LIVE':
                    try: kite.place_order(tradingsymbol=trade.symbol, exchange=trade.exchange, transaction_type=kite.TRANSACTION_TYPE_SELL,
                        quantity=qty_delta, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                    except Exception as e: log_event(trade, f"Broker Fail (Exit): {e}")
            else:
                return False

        db.session.commit()
        return True

def promote_to_live(kite, trade_ref):
    with trade_lock:
        trade = ActiveTrade.query.filter_by(trade_ref=str(trade_ref)).first()
        if trade and trade.mode == "PAPER":
            try:
                kite.place_order(tradingsymbol=trade.symbol, exchange=trade.exchange, transaction_type=kite.TRANSACTION_TYPE_BUY,
                    quantity=trade.quantity, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                trade.mode = "LIVE"
                trade.status = "PROMOTED_LIVE"
                log_event(trade, "Promoted to LIVE")
                db.session.commit()
                return True
            except: return False
    return False

def close_trade_manual(kite, trade_ref):
    with trade_lock:
        trade = ActiveTrade.query.filter_by(trade_ref=str(trade_ref)).first()
        if not trade: return False
        
        if trade.status == "PENDING":
            move_to_history_db(trade, "CANCELLED_MANUAL", 0)
            db.session.commit()
            return True
        
        exit_p = trade.current_ltp
        try: exit_p = kite.quote(f"{trade.exchange}:{trade.symbol}")[f"{trade.exchange}:{trade.symbol}"]['last_price']
        except: pass

        if trade.mode == "LIVE":
            try: kite.place_order(tradingsymbol=trade.symbol, exchange=trade.exchange, transaction_type=kite.TRANSACTION_TYPE_SELL,
                    quantity=trade.quantity, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
            except: pass
        
        move_to_history_db(trade, "MANUAL_EXIT", exit_p)
        db.session.commit()
        return True

def delete_trade(trade_id):
    try:
        TradeHistory.query.filter_by(id=int(trade_id)).delete()
        db.session.commit()
        return True
    except:
        db.session.rollback()
        return False

def move_to_history_db(trade_obj, final_status, exit_price):
    """Moves ActiveTrade Row to TradeHistory JSON Blob"""
    # 1. Calculate Finals
    real_pnl = 0
    was_active = trade_obj.status != 'PENDING'
    if was_active:
        real_pnl = round((exit_price - trade_obj.entry_price) * trade_obj.quantity, 2)
    
    # 2. Update Object for export
    trade_dict = trade_obj.to_dict()
    trade_dict['status'] = final_status
    trade_dict['exit_price'] = exit_price
    trade_dict['exit_time'] = get_time_str()
    trade_dict['exit_type'] = final_status
    trade_dict['pnl'] = real_pnl
    
    # Append final logs
    logs = trade_dict['logs']
    logs.append(f"[{get_time_str()}] Closed: {final_status} @ {exit_price} | P/L ₹ {real_pnl:.2f}")
    if was_active:
        made_high = trade_obj.made_high
        max_pnl = (made_high - trade_obj.entry_price) * trade_obj.quantity
        logs.append(f"[{get_time_str()}] Info: Made High: {made_high} | Max P/L ₹ {max_pnl:.2f}")
    
    trade_dict['logs'] = logs
    
    # 3. Create History Record & Delete Active
    hist = TradeHistory(id=trade_obj.id, data=json.dumps(trade_dict))
    db.session.add(hist)
    db.session.delete(trade_obj)

def load_history():
    try:
        return [json.loads(r.data) for r in TradeHistory.query.order_by(TradeHistory.id.desc()).all()]
    except: return []
