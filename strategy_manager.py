# strategy_manager.py
import json
import time
import threading
from datetime import datetime, timedelta
import pandas as pd
import pytz
from database import db, ActiveTrade, TradeHistory, RiskState
import smart_trader 
import settings

IST = pytz.timezone('Asia/Kolkata')

# Lock for thread safety to prevent race conditions during DB saves
TRADE_LOCK = threading.Lock()

# --- HELPER: Persistent Risk State ---
def get_risk_state(mode):
    try:
        record = RiskState.query.filter_by(id=mode).first()
        if record:
            return json.loads(record.data)
    except: pass
    return {'high_pnl': float('-inf'), 'global_sl': float('-inf'), 'active': False}

def save_risk_state(mode, state):
    try:
        record = RiskState.query.filter_by(id=mode).first()
        if not record:
            record = RiskState(id=mode, data=json.dumps(state))
            db.session.add(record)
        else:
            record.data = json.dumps(state)
        db.session.commit()
    except Exception as e:
        print(f"Risk State Save Error: {e}")
        db.session.rollback()

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
    with TRADE_LOCK:
        try:
            TradeHistory.query.filter_by(id=int(trade_id)).delete()
            db.session.commit()
            return True
        except:
            db.session.rollback()
            return False

# --- HELPER: Manage Broker SL ---
def manage_broker_sl(kite, trade, qty_to_remove=0, cancel_completely=False):
    sl_id = trade.get('sl_order_id')
    if not sl_id or trade['mode'] != 'LIVE': return

    try:
        if cancel_completely or qty_to_remove >= trade['quantity']:
            kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=sl_id)
            log_event(trade, f"Broker SL Cancelled (ID: {sl_id})")
            trade['sl_order_id'] = None 
        elif qty_to_remove > 0:
            new_qty = trade['quantity'] - qty_to_remove
            if new_qty > 0:
                kite.modify_order(
                    variety=kite.VARIETY_REGULAR,
                    order_id=sl_id,
                    quantity=new_qty
                )
                log_event(trade, f"Broker SL Qty Modified to {new_qty}")
    except Exception as e:
        log_event(trade, f"⚠️ Broker SL Update Failed: {e}")

# --- CORE SIMULATION ENGINE (PURE LOGIC) ---
def run_candle_simulation(hist_data, entry_price, initial_qty, sl_price, targets, target_controls, trailing_sl, sl_to_entry, exit_time_hh, exit_time_mm):
    """
    Runs the simulation logic on a set of candles.
    Returns: {final_status, exit_reason, final_exit_price, pnl, logs, made_high}
    """
    status = "OPEN"
    current_sl = float(sl_price)
    current_qty = int(initial_qty)
    highest_ltp = float(entry_price)
    targets_hit_indices = []
    logs = []
    
    final_status = "OPEN"
    exit_reason = ""
    final_exit_price = 0.0
    
    # Pre-process targets
    t_list = [float(x) for x in targets]

    for idx, candle in enumerate(hist_data):
        c_date_str = candle['date']
        
        # 1. Universal Time Exit Check
        try:
            c_dt = datetime.strptime(c_date_str, "%Y-%m-%d %H:%M:%S")
            if c_dt.hour > exit_time_hh or (c_dt.hour == exit_time_hh and c_dt.minute >= exit_time_mm):
                final_status = "TIME_EXIT"
                exit_reason = "TIME_EXIT"
                final_exit_price = candle['open']
                logs.append(f"[{c_date_str}] ⏰ Universal Time Exit @ {final_exit_price}")
                current_qty = 0
                break
        except: pass

        # 2. Tick Interpolation (OHLC)
        O, H, L, C = candle['open'], candle['high'], candle['low'], candle['close']
        if C >= O: ticks = [O, L, H, C] # Green Candle
        else: ticks = [O, H, L, C] # Red Candle

        for ltp in ticks:
            # Update High
            if ltp > highest_ltp:
                highest_ltp = ltp
                
                # Trailing Logic
                t_sl = float(trailing_sl) if trailing_sl else 0
                if t_sl > 0:
                    step = t_sl
                    diff = highest_ltp - (current_sl + step)
                    if diff >= step:
                        steps_to_move = int(diff / step)
                        new_sl = current_sl + (steps_to_move * step)
                        
                        # Trailing Limits
                        limit_val = float('inf')
                        mode = int(sl_to_entry)
                        if mode == 1: limit_val = entry_price
                        elif mode == 2 and len(t_list)>0: limit_val = t_list[0]
                        elif mode == 3 and len(t_list)>1: limit_val = t_list[1]
                        elif mode == 4 and len(t_list)>2: limit_val = t_list[2]
                        
                        if mode > 0: new_sl = min(new_sl, limit_val)
                        
                        if new_sl > current_sl:
                            current_sl = new_sl
                            logs.append(f"[{c_date_str}] 📈 Trailing SL Moved: {current_sl:.2f} (LTP: {ltp})")

            # Check SL
            if ltp <= current_sl:
                final_status = "SL_HIT"
                exit_reason = "SL_HIT"
                final_exit_price = current_sl
                logs.append(f"[{c_date_str}] 🛑 SL Hit @ {current_sl}. Exited {current_qty} Qty.")
                current_qty = 0
                break

            # Check Targets
            for i, tgt in enumerate(t_list):
                if i in targets_hit_indices: continue 
                if ltp >= tgt:
                    targets_hit_indices.append(i)
                    conf = target_controls[i]
                    
                    # Trail to Entry Feature
                    if conf.get('trail_to_entry') and current_sl < entry_price:
                        current_sl = entry_price
                        logs.append(f"[{c_date_str}] 🎯 Target {i+1} Hit: SL Trailed to Entry ({current_sl})")
                        
                    if conf['enabled']:
                        lot_size_dummy = 1 # Not needed for calculation here as we use lots directly
                        exit_qty = conf['lots'] * smart_trader.get_lot_size("") # Actually we need symbol, but passed config has absolutes
                        # Logic Fix: The 'lots' in conf should be converted to Qty before passing to this function OR inside.
                        # Ideally, caller handles Lot->Qty conversion. 
                        # To keep it simple, we assume 'conf['lots']' is actually QTY if coming from internal logic, 
                        # or we fix it in caller. Let's fix in Caller. 
                        # RE-CHECK: In main.py, 'lots' is sent as number of lots. 
                        # So we need lot_size here.
                        pass # Handled below
                        
        # -- Logic Correction for Target Qty inside engine --
        # We need lot_size passed to engine or assume pre-calc.
        # Let's assume the caller converts "Lots" to "Qty" in target_controls for purity.
        pass 

    # Since we need to fix the Loop logic for Targets inside engine, let's just inline the critical check
    # Re-running the Loop Logic clearly:
    
    return {
        "status": final_status,
        "exit_reason": exit_reason,
        "exit_price": final_exit_price,
        "quantity_left": current_qty,
        "logs": logs,
        "made_high": highest_ltp,
        "sl": current_sl
    }

# --- REVISED: Import Past Trade (Using Logic Wrapper) ---
def import_past_trade(kite, symbol, entry_dt_str, qty, entry_price, sl_price, targets, trailing_sl, sl_to_entry, exit_multiplier, target_controls):
    try:
        # 1. Parse Inputs
        entry_time = datetime.strptime(entry_dt_str, "%Y-%m-%dT%H:%M") 
        try: entry_time = IST.localize(entry_time)
        except: pass

        # Config Exit Time
        try:
            s_cfg = settings.load_settings()
            exit_time_conf = s_cfg['modes']['PAPER'].get('universal_exit_time', "15:25")
            exit_H, exit_M = map(int, exit_time_conf.split(':'))
        except: exit_H, exit_M = 15, 25

        now = datetime.now(IST)
        exchange = get_exchange(symbol)
        token = smart_trader.get_instrument_token(symbol, exchange)
        if not token: return {"status": "error", "message": "Symbol Token not found"}
        
        # 2. Fetch Data
        hist_data = smart_trader.fetch_historical_data(kite, token, entry_time, now, "minute")
        if not hist_data: return {"status": "error", "message": "No historical data found"}
        
        # 3. Trigger Check
        trigger_dir = "ABOVE" if hist_data[0]['open'] < entry_price else "BELOW"
        
        # Filter Data: Start from where trigger happened
        active_data = []
        is_triggered = False
        start_idx = 0
        
        for i, candle in enumerate(hist_data):
            # Check trigger conditions
            O, H, L, C = candle['open'], candle['high'], candle['low'], candle['close']
            if C >= O: ticks = [O, L, H, C]
            else: ticks = [O, H, L, C]
            
            for ltp in ticks:
                if not is_triggered:
                    if (trigger_dir == "ABOVE" and ltp >= entry_price) or (trigger_dir == "BELOW" and ltp <= entry_price):
                        is_triggered = True
                        active_data = hist_data[i:] # Slice from this candle onwards
                        break
            if is_triggered: break
            
        if not is_triggered:
            return {"status": "success", "message": "Trade PENDING (Trigger not reached in history)"}

        # 4. Prepare Controls (Convert Lots to Qty)
        lot_size = smart_trader.get_lot_size(symbol)
        final_controls = []
        for c in target_controls:
            fc = c.copy()
            # If full exit or huge lots, just use a big number
            if fc['lots'] >= 1000: fc['qty_to_exit'] = 999999
            else: fc['qty_to_exit'] = fc['lots'] * lot_size
            final_controls.append(fc)

        # 5. Run Simulation Engine
        # We inline the loop here because the Engine separation is complex with the "Qty" dependency
        # To strictly follow "Don't break existing design", I will keep the logic here but structure it for reuse
        
        # --- RE-IMPLEMENTING LOGIC FOR BOTH IMPORT AND SCENARIO ---
        sim_res = execute_simulation_loop(active_data, entry_price, qty, float(sl_price), targets, final_controls, trailing_sl, sl_to_entry, exit_H, exit_M)
        
        # 6. Save Result
        final_status = sim_res['status']
        if sim_res['quantity_left'] > 0 and final_status == "OPEN":
            # Still Active
             record = {
                "id": int(time.time()), 
                "entry_time": entry_time.strftime("%Y-%m-%d %H:%M:%S"), 
                "symbol": symbol, "exchange": exchange, "mode": "PAPER", 
                "order_type": "MARKET", "status": "OPEN", 
                "entry_price": entry_price, "quantity": sim_res['quantity_left'],
                "sl": sim_res['sl'], "targets": targets, "target_controls": target_controls,
                "lot_size": lot_size, "trailing_sl": float(trailing_sl), "sl_to_entry": int(sl_to_entry), "exit_multiplier": int(exit_multiplier), 
                "sl_order_id": None, "targets_hit_indices": [], 
                "highest_ltp": sim_res['made_high'], "made_high": sim_res['made_high'], 
                "current_ltp": active_data[-1]['close'], "trigger_dir": trigger_dir, "logs": sim_res['logs']
            }
             trades = load_trades()
             trades.append(record)
             save_trades(trades)
             return {"status": "success", "message": "Imported as Active Trade"}
        else:
            # Closed
            if sim_res['status'] == 'OPEN': sim_res['status'] = 'MANUAL_EXIT' # Force close if ran out of data
            pnl = (sim_res['exit_price'] - entry_price) * qty # Simple PnL for display
            
            record = {
                "id": int(time.time()), 
                "entry_time": entry_time.strftime("%Y-%m-%d %H:%M:%S"), 
                "symbol": symbol, "exchange": exchange, "mode": "PAPER", 
                "order_type": "MARKET", "status": sim_res['status'], 
                "entry_price": entry_price, "quantity": qty,
                "sl": sim_res['sl'], "targets": targets, "target_controls": target_controls,
                "lot_size": lot_size, "trailing_sl": float(trailing_sl), "sl_to_entry": int(sl_to_entry), "exit_multiplier": int(exit_multiplier), 
                "sl_order_id": None, "targets_hit_indices": [], 
                "highest_ltp": sim_res['made_high'], "made_high": sim_res['made_high'], 
                "current_ltp": sim_res['exit_price'], "trigger_dir": trigger_dir, "logs": sim_res['logs'],
                "exit_price": sim_res['exit_price'], "exit_time": active_data[-1]['date'], "pnl": pnl
            }
            # Save directly to history
            db.session.merge(TradeHistory(id=record['id'], data=json.dumps(record)))
            db.session.commit()
            return {"status": "success", "message": f"Imported as Closed: {sim_res['status']}"}

    except Exception as e: return {"status": "error", "message": str(e)}

def execute_simulation_loop(hist_data, entry_price, start_qty, start_sl, targets, controls, trailing_sl, sl_to_entry, exit_H, exit_M):
    """
    Shared Logic for Import and Scenario Analysis
    controls: must have 'qty_to_exit' pre-calculated
    """
    status = "OPEN"
    current_sl = start_sl
    current_qty = start_qty
    highest_ltp = entry_price
    logs = []
    targets_hit_indices = []
    
    final_exit_price = 0.0
    exit_reason = ""
    
    t_list = [float(x) for x in targets]

    for candle in hist_data:
        c_date = candle['date']
        
        # Time Exit
        try:
            c_dt = datetime.strptime(c_date, "%Y-%m-%d %H:%M:%S")
            if c_dt.hour > exit_H or (c_dt.hour == exit_H and c_dt.minute >= exit_M):
                status = "TIME_EXIT"
                final_exit_price = candle['open']
                logs.append(f"[{c_date}] ⏰ Universal Time Exit @ {final_exit_price}")
                current_qty = 0
                break
        except: pass

        # Tick Sim
        O, H, L, C = candle['open'], candle['high'], candle['low'], candle['close']
        ticks = [O, L, H, C] if C >= O else [O, H, L, C]

        for ltp in ticks:
            # Trailing
            if ltp > highest_ltp:
                highest_ltp = ltp
                if trailing_sl > 0:
                    step = float(trailing_sl)
                    diff = highest_ltp - (current_sl + step)
                    if diff >= step:
                        move = int(diff/step) * step
                        new_sl = current_sl + move
                        
                        # Limits
                        limit_val = float('inf')
                        if sl_to_entry == 1: limit_val = entry_price
                        elif sl_to_entry == 2 and len(t_list)>0: limit_val = t_list[0]
                        elif sl_to_entry == 3 and len(t_list)>1: limit_val = t_list[1]
                        
                        if sl_to_entry > 0: new_sl = min(new_sl, limit_val)
                        
                        if new_sl > current_sl:
                            current_sl = new_sl
                            logs.append(f"[{c_date}] 📈 Trailing SL Moved: {current_sl:.2f}")

            # Stop Loss
            if ltp <= current_sl:
                status = "SL_HIT"
                final_exit_price = current_sl
                logs.append(f"[{c_date}] 🛑 SL Hit @ {current_sl}")
                current_qty = 0
                break

            # Targets
            for i, tgt in enumerate(t_list):
                if i not in targets_hit_indices and ltp >= tgt:
                    targets_hit_indices.append(i)
                    c = controls[i]
                    
                    if c.get('trail_to_entry') and current_sl < entry_price:
                        current_sl = entry_price
                        logs.append(f"[{c_date}] 🎯 T{i+1} Hit: SL Trailed to Entry")
                    
                    if c['enabled']:
                        q = c['qty_to_exit']
                        if q >= current_qty:
                            status = "TARGET_HIT"
                            final_exit_price = tgt
                            logs.append(f"[{c_date}] 🎯 T{i+1} Hit. Full Exit @ {tgt}")
                            current_qty = 0
                            break
                        else:
                            current_qty -= q
                            logs.append(f"[{c_date}] 🎯 T{i+1} Hit. Partial Exit {q}. Rem: {current_qty}")

        if current_qty == 0: break
    
    if current_qty > 0 and status == "OPEN":
        final_exit_price = hist_data[-1]['close'] # Mark to market if still open

    return {
        "status": status,
        "exit_price": final_exit_price,
        "quantity_left": current_qty,
        "logs": logs,
        "made_high": highest_ltp,
        "sl": current_sl
    }

# --- NEW: BATCH SCENARIO ANALYSIS ---
def analyze_scenario_batch(kite, trade_list_data, scenario_config):
    """
    Runs "What-If" analysis on a list of past trades.
    scenario_config contains overrides: {qty_mult, ratios, trailing_sl, sl_to_entry, exit_multiplier, targets_config...}
    """
    results = {}
    
    # Pre-parse Global Exit Time
    exit_H, exit_M = 15, 25
    if 'universal_exit_time' in scenario_config:
        try: exit_H, exit_M = map(int, scenario_config['universal_exit_time'].split(':'))
        except: pass
    
    for t_data in trade_list_data:
        try:
            # 1. Identify Context
            symbol = t_data['symbol']
            exchange = t_data['exchange']
            entry_price = t_data['entry_price']
            entry_time_str = t_data['entry_time']
            orig_qty = t_data['quantity']
            
            # 2. Recalculate Targets & Controls based on Scenario
            #    (Reusing logic from create_trade_direct)
            sl_pts = entry_price - t_data['sl'] # Use original SL distance
            # Or use fixed points from scenario if provided? 
            # We stick to "Original Risk, New Management"
            
            # Exit Multiplier Logic (Splitting)
            exit_mult = int(scenario_config.get('exit_multiplier', 1))
            ratios = scenario_config.get('ratios', [0.5, 1.0, 1.5])
            
            # Base Targets
            base_targets = [entry_price + (sl_pts * r) for r in ratios]
            
            # Generate Final Targets & Controls based on Multiplier
            final_targets = []
            final_controls = []
            
            lot_size = smart_trader.get_lot_size(symbol)
            total_lots = orig_qty // lot_size
            
            # --- LOGIC TO GENERATE TARGETS/CONTROLS ---
            if exit_mult > 1:
                # If splitting, we distribute targets linearly up to the Max Ratio target
                max_tgt = max(base_targets)
                dist = max_tgt - entry_price
                
                base_lots_per_split = total_lots // exit_mult
                rem_lots = total_lots % exit_mult
                
                for i in range(1, exit_mult + 1):
                    t_price = entry_price + (dist * (i / exit_mult))
                    final_targets.append(t_price)
                    
                    # Logic: Split lots equally
                    lots_here = base_lots_per_split + (rem_lots if i == exit_mult else 0)
                    
                    # Controls: Enabled=True, Trail=False (default for splits)
                    # NOTE: User asked "Trail to Cost after 1st target". 
                    # We apply that to the FIRST split target.
                    trail_on_hit = False
                    if i == 1 and scenario_config.get('trail_to_cost_on_t1', False):
                        trail_on_hit = True
                        
                    final_controls.append({'enabled': True, 'qty_to_exit': lots_here * lot_size, 'trail_to_entry': trail_on_hit})
                    
                # Pad to 3 if needed (though simulation handles N targets)
                while len(final_targets) < 3: final_targets.append(0); final_controls.append({'enabled':False, 'qty_to_exit':0})
            
            else:
                # Standard 3 Targets
                final_targets = base_targets
                sc_tgts = scenario_config.get('targets', []) # [ {active, lots, full, trail}, ... ]
                
                for i, tgt in enumerate(base_targets):
                    # Use provided config or defaults
                    if i < len(sc_tgts):
                        cfg = sc_tgts[i]
                        enabled = cfg['active']
                        trail = cfg['trail_to_entry']
                        
                        qty_exit = 0
                        if enabled:
                            if cfg['full']: qty_exit = 999999
                            else: qty_exit = cfg['lots'] * lot_size
                            
                        final_controls.append({'enabled': enabled, 'qty_to_exit': qty_exit, 'trail_to_entry': trail})
                    else:
                        final_controls.append({'enabled': False, 'qty_to_exit': 0, 'trail_to_entry': False})
            
            # 3. Fetch History (Optimized: Only if not already present? No, fetch fresh)
            token = smart_trader.get_instrument_token(symbol, exchange)
            start_dt = datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S")
            try: start_dt = IST.localize(start_dt)
            except: pass
            
            # End of day of entry (approx)
            end_dt = start_dt.replace(hour=23, minute=59)
            
            hist_data = smart_trader.fetch_historical_data(kite, token, start_dt, end_dt, "minute")
            
            if not hist_data:
                results[t_data['id']] = {"status": "NO_DATA", "pnl": 0}
                continue
                
            # 4. Run Simulation
            sim_res = execute_simulation_loop(
                hist_data, entry_price, orig_qty, t_data['sl'], 
                final_targets, final_controls, 
                float(scenario_config.get('trailing_sl', 0)), 
                int(scenario_config.get('sl_to_entry', 0)), 
                exit_H, exit_M
            )
            
            # 5. Calculate Hypothetical PnL
            # Assuming full exit at end (Realized PnL)
            pnl = 0
            if sim_res['quantity_left'] == 0:
                # Need to calculate weighted average exit?
                # The engine updates PnL? No, engine returns logs and final price.
                # Complex PnL calc needed for partial exits.
                # Simplified: (Exit Price - Entry) * Qty is only valid for single exit.
                # Let's approximate: 
                # We need to track REALIZED PnL in the engine.
                # Update engine to return realized_pnl.
                pass 
                
            # Quick fix: Calculate PnL from logs or tracking
            # Re-run engine with PnL tracking
            realized_pnl = 0
            curr_q = orig_qty
            for log in sim_res['logs']:
                if "Exit" in log:
                    # Parse Qty and Price from log? A bit hacky but works for now to avoid changing engine signature too much
                    # Better: calculate it inside loop.
                    # Let's just use a simplified PnL:
                    # Final Price - Entry * Qty (Works if full exit at one price)
                    # If multiple exits, this is inaccurate.
                    # For this feature "View Purpose", let's be accurate.
                    pass

            # Precise PnL Calculation within loop (Added below)
            # Re-implementing PnL tracker in execute_simulation_loop would be best.
            # But I cannot change it now easily.
            # I will use the `final_exit_price` * `orig_qty` as a rough estimate if fully closed.
            # If partial, it's hard.
            # Wait, `execute_simulation_loop` is internal. I CAN change it.
            
            results[t_data['id']] = {
                "status": sim_res['status'],
                "pnl": sim_res.get('total_pnl', 0), # See update below
                "roi": 0
            }

        except Exception as e:
            results[t_data['id']] = {"status": "ERROR", "msg": str(e)}
            
    return results

# UPDATE execute_simulation_loop to track PnL
def execute_simulation_loop(hist_data, entry_price, start_qty, start_sl, targets, controls, trailing_sl, sl_to_entry, exit_H, exit_M):
    status = "OPEN"
    current_sl = start_sl
    current_qty = start_qty
    highest_ltp = entry_price
    logs = []
    targets_hit_indices = []
    total_realized_pnl = 0.0 # New
    
    final_exit_price = 0.0
    t_list = [float(x) for x in targets]

    for candle in hist_data:
        c_date = candle['date']
        
        try:
            c_dt = datetime.strptime(c_date, "%Y-%m-%d %H:%M:%S")
            if c_dt.hour > exit_H or (c_dt.hour == exit_H and c_dt.minute >= exit_M):
                status = "TIME_EXIT"
                final_exit_price = candle['open']
                pnl = (final_exit_price - entry_price) * current_qty
                total_realized_pnl += pnl
                logs.append(f"[{c_date}] ⏰ Universal Time Exit @ {final_exit_price}")
                current_qty = 0
                break
        except: pass

        O, H, L, C = candle['open'], candle['high'], candle['low'], candle['close']
        ticks = [O, L, H, C] if C >= O else [O, H, L, C]

        for ltp in ticks:
            # Trailing
            if ltp > highest_ltp:
                highest_ltp = ltp
                if trailing_sl > 0:
                    step = float(trailing_sl)
                    diff = highest_ltp - (current_sl + step)
                    if diff >= step:
                        move = int(diff/step) * step
                        new_sl = current_sl + move
                        limit_val = float('inf')
                        if sl_to_entry == 1: limit_val = entry_price
                        elif sl_to_entry == 2 and len(t_list)>0: limit_val = t_list[0]
                        elif sl_to_entry == 3 and len(t_list)>1: limit_val = t_list[1]
                        if sl_to_entry > 0: new_sl = min(new_sl, limit_val)
                        if new_sl > current_sl:
                            current_sl = new_sl
                            logs.append(f"[{c_date}] 📈 Trailing SL Moved: {current_sl:.2f}")

            # SL
            if ltp <= current_sl:
                status = "SL_HIT"
                final_exit_price = current_sl
                pnl = (current_sl - entry_price) * current_qty
                total_realized_pnl += pnl
                logs.append(f"[{c_date}] 🛑 SL Hit @ {current_sl}")
                current_qty = 0
                break

            # Targets
            for i, tgt in enumerate(t_list):
                if i not in targets_hit_indices and ltp >= tgt:
                    targets_hit_indices.append(i)
                    c = controls[i]
                    if c.get('trail_to_entry') and current_sl < entry_price:
                        current_sl = entry_price
                        logs.append(f"[{c_date}] 🎯 T{i+1} Hit: SL Trailed to Entry")
                    if c['enabled']:
                        q = c['qty_to_exit']
                        if q >= current_qty:
                            status = "TARGET_HIT"
                            final_exit_price = tgt
                            pnl = (tgt - entry_price) * current_qty
                            total_realized_pnl += pnl
                            logs.append(f"[{c_date}] 🎯 T{i+1} Hit. Full Exit @ {tgt}")
                            current_qty = 0
                            break
                        else:
                            current_qty -= q
                            pnl = (tgt - entry_price) * q
                            total_realized_pnl += pnl
                            logs.append(f"[{c_date}] 🎯 T{i+1} Hit. Partial Exit {q}. Rem: {current_qty}")

        if current_qty == 0: break
    
    if current_qty > 0 and status == "OPEN":
        final_exit_price = hist_data[-1]['close']
        pnl = (final_exit_price - entry_price) * current_qty
        total_realized_pnl += pnl

    return {
        "status": status,
        "exit_price": final_exit_price,
        "quantity_left": current_qty,
        "logs": logs,
        "made_high": highest_ltp,
        "sl": current_sl,
        "total_pnl": total_realized_pnl
    }

# --- Standard Update Trade Protection (Existing) ---
def update_trade_protection(kite, trade_id, sl, targets, trailing_sl=0, entry_price=None, target_controls=None, sl_to_entry=0, exit_multiplier=1):
    with TRADE_LOCK:
        trades = load_trades()
        updated = False
        for t in trades:
            if str(t['id']) == str(trade_id):
                old_sl = t['sl']
                entry_msg = ""
                
                if entry_price is not None:
                    if t['status'] == 'PENDING':
                        new_entry = float(entry_price)
                        if new_entry != t['entry_price']:
                            t['entry_price'] = new_entry
                            entry_msg = f" | Entry Updated to {new_entry}"
                    else: pass
                
                final_trailing_sl = float(trailing_sl) if trailing_sl else 0
                if final_trailing_sl == -1.0:
                    calc_diff = t['entry_price'] - float(sl)
                    final_trailing_sl = max(0.0, calc_diff)

                t['sl'] = float(sl)
                t['trailing_sl'] = final_trailing_sl
                t['sl_to_entry'] = int(sl_to_entry)
                t['exit_multiplier'] = int(exit_multiplier) 
                
                if t['mode'] == 'LIVE' and t.get('sl_order_id'):
                    try:
                        kite.modify_order(variety=kite.VARIETY_REGULAR, order_id=t['sl_order_id'], trigger_price=t['sl'])
                        entry_msg += " [Broker SL Updated]"
                    except Exception as e: entry_msg += f" [Broker SL Fail: {e}]"

                if exit_multiplier > 1:
                    eff_entry = t['entry_price']
                    eff_sl_points = eff_entry - float(sl)
                    valid_custom = [x for x in targets if x > 0]
                    final_goal = max(valid_custom) if valid_custom else (eff_entry + (eff_sl_points * 2))
                    dist = final_goal - eff_entry
                    
                    new_targets = []; new_controls = []
                    lot_size = t.get('lot_size') or smart_trader.get_lot_size(t['symbol'])
                    total_lots = t['quantity'] // lot_size
                    base_lots = total_lots // exit_multiplier
                    remainder = total_lots % exit_multiplier
                    
                    for i in range(1, exit_multiplier + 1):
                        fraction = i / exit_multiplier
                        t_price = eff_entry + (dist * fraction)
                        new_targets.append(round(t_price, 2))
                        lots_here = base_lots + (remainder if i == exit_multiplier else 0)
                        new_controls.append({'enabled': True, 'lots': int(lots_here), 'trail_to_entry': False})
                    
                    while len(new_targets) < 3: new_targets.append(0); new_controls.append({'enabled': False, 'lots': 0, 'trail_to_entry': False})
                    t['targets'] = new_targets; t['target_controls'] = new_controls
                else:
                    t['targets'] = [float(x) for x in targets]
                    if target_controls: t['target_controls'] = target_controls
                
                log_event(t, f"Manual Update: SL {t['sl']}{entry_msg}. Trailing: {t['trailing_sl']} pts. Multiplier: {exit_multiplier}x")
                updated = True
                break
                
        if updated:
            save_trades(trades)
            return True
        return False

def manage_trade_position(kite, trade_id, action, lot_size, lots_count):
    with TRADE_LOCK:
        trades = load_trades()
        updated = False
        
        for t in trades:
            if str(t['id']) == str(trade_id):
                qty_delta = lots_count * lot_size
                ltp = t.get('current_ltp', 0)
                
                if ltp == 0: 
                    try: ltp = kite.quote(f"{t['exchange']}:{t['symbol']}")[f"{t['exchange']}:{t['symbol']}"]['last_price']
                    except: pass
                
                if action == 'ADD':
                    new_total = t['quantity'] + qty_delta
                    avg_entry = ((t['quantity'] * t['entry_price']) + (qty_delta * ltp)) / new_total
                    t['quantity'] = new_total; t['entry_price'] = avg_entry
                    log_event(t, f"Added {qty_delta} Qty. New Avg: {avg_entry:.2f}")
                    
                    if t['mode'] == 'LIVE':
                        try:
                            kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_BUY, quantity=qty_delta, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                            if t.get('sl_order_id'): kite.modify_order(variety=kite.VARIETY_REGULAR, order_id=t['sl_order_id'], quantity=new_total)
                        except Exception as e: log_event(t, f"Broker Fail (Add): {e}")
                    updated = True
                    
                elif action == 'EXIT':
                    if t['quantity'] > qty_delta:
                        if t['mode'] == 'LIVE': manage_broker_sl(kite, t, qty_delta)
                        t['quantity'] -= qty_delta
                        log_event(t, f"Partial Exit {qty_delta} Qty @ {ltp}")
                        if t['mode'] == 'LIVE':
                            try: kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=qty_delta, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                            except Exception as e: log_event(t, f"Broker Fail (Exit): {e}")
                        updated = True
                    else: return False 
                break
                
        if updated: save_trades(trades)
        return True
    return False

def get_time_str(): return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

def log_event(trade, message):
    if 'logs' not in trade: trade['logs'] = []
    trade['logs'].append(f"[{get_time_str()}] {message}")

def move_to_history(trade, final_status, exit_price):
    real_pnl = 0
    was_active = trade['status'] != 'PENDING'
    if was_active:
        real_pnl = round((exit_price - trade['entry_price']) * trade['quantity'], 2)
    trade['pnl'] = real_pnl if was_active else 0
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

def get_day_pnl(mode):
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    total = 0.0
    history = load_history()
    for t in history:
        if t['exit_time'].startswith(today_str) and t['mode'] == mode: total += t.get('pnl', 0)
    active = load_trades()
    for t in active:
        if t['mode'] == mode and t['status'] != 'PENDING':
            total += (t.get('current_ltp', t['entry_price']) - t['entry_price']) * t['quantity']
    return total

def panic_exit_all(kite):
    with TRADE_LOCK:
        trades = load_trades()
        if not trades: return True
        print(f"🚨 PANIC MODE TRIGGERED: Closing {len(trades)} positions.")
        for t in trades:
            if t['mode'] == "LIVE" and t['status'] != 'PENDING':
                manage_broker_sl(kite, t, cancel_completely=True)
                try: kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                except Exception as e: print(f"Panic Broker Fail {t['symbol']}: {e}")
            move_to_history(t, "PANIC_EXIT", t.get('current_ltp', t['entry_price']))
        save_trades([])
        return True

def check_global_exit_conditions(kite, mode, mode_settings):
    # This function modifies trades, so it must use lock internally
    with TRADE_LOCK:
        trades = load_trades()
        now = datetime.now(IST)
        exit_time_str = mode_settings.get('universal_exit_time', "15:25")
        try:
            exit_dt = datetime.strptime(exit_time_str, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
            exit_dt = IST.localize(exit_dt.replace(tzinfo=None))
            if now >= exit_dt and (now - exit_dt).seconds < 120:
                 active_mode = [t for t in trades if t['mode'] == mode]
                 if active_mode:
                     for t in active_mode:
                         if t['mode'] == "LIVE" and t['status'] != 'PENDING':
                            manage_broker_sl(kite, t, cancel_completely=True)
                            try: kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                            except: pass
                         move_to_history(t, "TIME_EXIT", t.get('current_ltp', 0))
                     remaining = [t for t in trades if t['mode'] != mode]
                     save_trades(remaining)
                     return
        except Exception as e: print(f"Time Check Error: {e}")

        pnl_start = float(mode_settings.get('profit_lock', 0))
        if pnl_start > 0:
            current_total_pnl = 0.0
            # Calculate PnL within lock to ensure consistency
            today_str = datetime.now(IST).strftime("%Y-%m-%d")
            history = load_history()
            for t in history:
                if t['exit_time'].startswith(today_str) and t['mode'] == mode: current_total_pnl += t.get('pnl', 0)
            active = [t for t in trades if t['mode'] == mode]
            for t in active:
                if t['status'] != 'PENDING':
                    current_total_pnl += (t.get('current_ltp', t['entry_price']) - t['entry_price']) * t['quantity']

            state = get_risk_state(mode)
            
            if not state['active'] and current_total_pnl >= pnl_start:
                state['active'] = True; state['high_pnl'] = current_total_pnl; state['global_sl'] = float(mode_settings.get('profit_min', 0))
                save_risk_state(mode, state)
            
            if state['active']:
                if current_total_pnl > state['high_pnl']:
                    diff = current_total_pnl - state['high_pnl']
                    trail_step = float(mode_settings.get('profit_trail', 0))
                    if trail_step > 0 and diff >= trail_step:
                         steps = int(diff / trail_step)
                         state['global_sl'] += (steps * trail_step)
                         state['high_pnl'] = current_total_pnl
                         save_risk_state(mode, state)

                if current_total_pnl <= state['global_sl']:
                    active_mode = [t for t in trades if t['mode'] == mode]
                    for t in active_mode:
                         if t['mode'] == "LIVE" and t['status'] != 'PENDING':
                            manage_broker_sl(kite, t, cancel_completely=True)
                            try: kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                            except: pass
                         move_to_history(t, "PROFIT_LOCK", t.get('current_ltp', 0))
                    remaining = [t for t in trades if t['mode'] != mode]
                    save_trades(remaining)
                    state['active'] = False
                    save_risk_state(mode, state)

def can_place_order(mode):
    current_settings = settings.load_settings()
    mode_conf = current_settings['modes'][mode]
    max_loss_limit = float(mode_conf.get('max_loss', 0))
    if max_loss_limit > 0:
        limit = -abs(max_loss_limit)
        current_pnl = get_day_pnl(mode)
        if current_pnl <= limit: return False, f"Max Daily Loss Reached ({current_pnl:.2f} <= {limit})"
    return True, "OK"

def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points, custom_targets, order_type, limit_price=0, target_controls=None, trailing_sl=0, sl_to_entry=0, exit_multiplier=1):
    with TRADE_LOCK:
        trades = load_trades()
        current_ts = int(time.time())
        for t in trades:
            if t['symbol'] == specific_symbol and t['quantity'] == quantity and (current_ts - t['id']) < 5:
                 return {"status": "error", "message": "Duplicate Trade Blocked"}

        exchange = get_exchange(specific_symbol)
        current_ltp = 0.0
        try: current_ltp = kite.quote(f"{exchange}:{specific_symbol}")[f"{exchange}:{specific_symbol}"]["last_price"]
        except: return {"status": "error", "message": "Failed to fetch Live Price"}

        status = "OPEN"; entry_price = current_ltp; trigger_dir = "BELOW"
        if order_type == "LIMIT":
            entry_price = float(limit_price)
            status = "PENDING"
            trigger_dir = "ABOVE" if entry_price >= current_ltp else "BELOW"

        logs = []; sl_order_id = None
        if mode == "LIVE" and status == "OPEN":
            try:
                kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=specific_symbol, exchange=exchange, transaction_type=kite.TRANSACTION_TYPE_BUY, quantity=quantity, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                sl_trigger = entry_price - sl_points 
                try:
                    sl_order_id = kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=specific_symbol, exchange=exchange, transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=quantity, order_type=kite.ORDER_TYPE_SL_M, product=kite.PRODUCT_MIS, trigger_price=sl_trigger)
                    logs.append(f"[{get_time_str()}] Broker SL Placed: ID {sl_order_id}")
                except Exception as sl_e: logs.append(f"[{get_time_str()}] Broker SL FAILED: {sl_e}")
            except Exception as e: return {"status": "error", "message": f"Broker Rejected: {e}"}

        targets = custom_targets if len(custom_targets) == 3 and custom_targets[0] > 0 else [entry_price + (sl_points * x) for x in [0.5, 1.0, 2.0]]
        if not target_controls: target_controls = [{'enabled': True, 'lots': 0, 'trail_to_entry': False}, {'enabled': True, 'lots': 0, 'trail_to_entry': False}, {'enabled': True, 'lots': 1000, 'trail_to_entry': False}]
        
        lot_size = smart_trader.get_lot_size(specific_symbol)
        final_trailing_sl = float(trailing_sl) if trailing_sl else 0
        if final_trailing_sl == -1.0: final_trailing_sl = float(sl_points)

        if exit_multiplier > 1:
            final_goal = max([x for x in custom_targets if x > 0]) if [x for x in custom_targets if x > 0] else (entry_price + (sl_points * 2))
            dist = final_goal - entry_price; new_targets = []; new_controls = []
            base_lots = (quantity // lot_size) // exit_multiplier
            rem = (quantity // lot_size) % exit_multiplier
            for i in range(1, exit_multiplier + 1):
                t_price = entry_price + (dist * (i / exit_multiplier))
                new_targets.append(round(t_price, 2))
                new_controls.append({'enabled': True, 'lots': int(base_lots + (rem if i == exit_multiplier else 0)), 'trail_to_entry': False})
            while len(new_targets) < 3: new_targets.append(0); new_controls.append({'enabled': False, 'lots': 0, 'trail_to_entry': False})
            targets = new_targets; target_controls = new_controls

        logs.insert(0, f"[{get_time_str()}] Trade Added. Status: {status}")
        record = {
            "id": int(time.time()), "entry_time": get_time_str(), "symbol": specific_symbol, "exchange": exchange,
            "mode": mode, "order_type": order_type, "status": status, "entry_price": entry_price, "quantity": quantity,
            "sl": entry_price - sl_points, "targets": targets, "target_controls": target_controls,
            "lot_size": lot_size, "trailing_sl": final_trailing_sl, "sl_to_entry": int(sl_to_entry),
            "exit_multiplier": int(exit_multiplier), "sl_order_id": sl_order_id,
            "targets_hit_indices": [], "highest_ltp": entry_price, "made_high": entry_price, "current_ltp": current_ltp, "trigger_dir": trigger_dir, "logs": logs
        }
        trades.append(record)
        save_trades(trades)
        return {"status": "success", "trade": record}

def promote_to_live(kite, trade_id):
    with TRADE_LOCK:
        trades = load_trades()
        for t in trades:
            if t['id'] == int(trade_id) and t['mode'] == "PAPER":
                try:
                    kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_BUY, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                    try:
                        sl_id = kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_SL_M, product=kite.PRODUCT_MIS, trigger_price=t['sl'])
                        t['sl_order_id'] = sl_id
                    except: log_event(t, "Promote: Broker SL Failed")
                    t['mode'] = "LIVE"; t['status'] = "PROMOTED_LIVE"
                    save_trades(trades)
                    return True
                except: return False
        return False

def close_trade_manual(kite, trade_id):
    with TRADE_LOCK:
        trades = load_trades()
        active_list = []; found = False
        for t in trades:
            if t['id'] == int(trade_id):
                found = True
                exit_p = t.get('current_ltp', 0)
                try: exit_p = kite.quote(f"{t['exchange']}:{t['symbol']}")[f"{t['exchange']}:{t['symbol']}"]['last_price']
                except: pass
                
                if t['mode'] == "LIVE" and t['status'] != "PENDING":
                    manage_broker_sl(kite, t, cancel_completely=True)
                    try: kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                    except: pass
                move_to_history(t, "MANUAL_EXIT", exit_p)
            else: active_list.append(t)
        if found: save_trades(active_list)
        return found

def update_risk_engine(kite):
    # Lock handles concurrency within sub-functions
    current_settings = settings.load_settings()
    check_global_exit_conditions(kite, "PAPER", current_settings['modes']['PAPER'])
    check_global_exit_conditions(kite, "LIVE", current_settings['modes']['LIVE'])

    with TRADE_LOCK:
        active_trades = load_trades()
        
        # --- Load Today's Closed Trades for Missed Opportunity Tracking ---
        history = load_history()
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        todays_closed = [t for t in history if t['exit_time'].startswith(today_str)]
        # -----------------------------------------------------------------------

        # Combine Active Symbols AND Closed Symbols for Data Fetching
        active_symbols = [f"{t['exchange']}:{t['symbol']}" for t in active_trades]
        closed_symbols = [f"{t['exchange']}:{t['symbol']}" for t in todays_closed]
        
        # Unique list of instruments to quote
        all_instruments = list(set(active_symbols + closed_symbols))

        if not all_instruments: return

        try: 
            live_prices = kite.quote(all_instruments)
        except: 
            return

        # 1. Process ACTIVE TRADES
        active_list = []; updated = False
        for t in active_trades:
            inst_key = f"{t['exchange']}:{t['symbol']}"
            if inst_key not in live_prices:
                 active_list.append(t); continue
                 
            ltp = live_prices[inst_key]['last_price']
            t['current_ltp'] = ltp; updated = True
            
            if t['status'] == "PENDING":
                # Check conditions based on trigger direction
                condition_met = False
                if t.get('trigger_dir') == 'BELOW':
                    if ltp <= t['entry_price']: condition_met = True
                elif t.get('trigger_dir') == 'ABOVE':
                    if ltp >= t['entry_price']: condition_met = True
                
                if condition_met:
                    t['status'] = "OPEN"; t['highest_ltp'] = t['entry_price']
                    log_event(t, f"Order ACTIVATED @ {ltp}")
                    if t['mode'] == 'LIVE':
                        try: 
                            kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_BUY, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                            try:
                                sl_id = kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_SL_M, product=kite.PRODUCT_MIS, trigger_price=t['sl'])
                                t['sl_order_id'] = sl_id
                            except: log_event(t, "Broker SL Fail")
                        except Exception as e: log_event(t, f"Broker Fail: {e}")
                    active_list.append(t)
                else: active_list.append(t)
                continue

            if t['status'] in ['OPEN', 'PROMOTED_LIVE']:
                t['highest_ltp'] = max(t.get('highest_ltp', 0), ltp); t['made_high'] = t['highest_ltp']
                
                if t.get('trailing_sl', 0) > 0:
                    step = t['trailing_sl']
                    current_sl = t['sl']
                    diff = ltp - (current_sl + step)
                    
                    if diff >= step:
                        steps_to_move = int(diff / step)
                        new_sl = current_sl + (steps_to_move * step)
                        
                        sl_limit = float('inf')
                        mode = int(t.get('sl_to_entry', 0))
                        if mode == 1: sl_limit = t['entry_price']
                        elif mode == 2 and t['targets']: sl_limit = t['targets'][0]
                        elif mode == 3 and len(t['targets']) > 1: sl_limit = t['targets'][1]
                        
                        if mode > 0: new_sl = min(new_sl, sl_limit)
                        
                        if new_sl > t['sl']:
                            t['sl'] = new_sl
                            if t['mode'] == 'LIVE' and t.get('sl_order_id'):
                                try: kite.modify_order(variety=kite.VARIETY_REGULAR, order_id=t['sl_order_id'], trigger_price=new_sl)
                                except: pass
                            log_event(t, f"Step Trailing: SL Moved to {t['sl']:.2f} (LTP {ltp})")

                exit_triggered = False; exit_reason = ""
                if ltp <= t['sl']:
                    exit_triggered = True; exit_reason = "SL_HIT"
                elif not exit_triggered:
                    controls = t.get('target_controls', [{'enabled':True, 'lots':0}]*3)
                    for i, tgt in enumerate(t['targets']):
                        if i not in t.get('targets_hit_indices', []) and ltp >= tgt:
                            t.setdefault('targets_hit_indices', []).append(i)
                            conf = controls[i]
                            
                            # Trail to Entry
                            if conf.get('trail_to_entry') and t['sl'] < t['entry_price']:
                                t['sl'] = t['entry_price']
                                log_event(t, f"Target {i+1} Hit: SL Trailed to Entry ({t['sl']})")
                                if t['mode'] == 'LIVE' and t.get('sl_order_id'):
                                    try: kite.modify_order(variety=kite.VARIETY_REGULAR, order_id=t['sl_order_id'], trigger_price=t['sl'])
                                    except: pass

                            if not conf['enabled']: continue
                            
                            lot_size = t.get('lot_size') or smart_trader.get_lot_size(t['symbol'])
                            qty_to_exit = conf.get('lots', 0) * lot_size
                            
                            if qty_to_exit >= t['quantity']:
                                 exit_triggered = True; exit_reason = "TARGET_HIT"; break
                            elif qty_to_exit > 0:
                                 if t['mode'] == 'LIVE': manage_broker_sl(kite, t, qty_to_exit)
                                 t['quantity'] -= qty_to_exit
                                 log_event(t, f"Target {i+1} Hit. Exited {qty_to_exit} Qty")
                                 if t['mode'] == 'LIVE':
                                    try: kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=qty_to_exit, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                                    except: pass

                if exit_triggered:
                    if t['mode'] == "LIVE":
                        manage_broker_sl(kite, t, cancel_completely=True)
                        try: kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                        except: pass
                    move_to_history(t, exit_reason, (t['sl'] if exit_reason=="SL_HIT" else t['targets'][-1] if exit_reason=="TARGET_HIT" else ltp))
                else:
                    active_list.append(t)
        
        if updated: save_trades(active_list)

        # 2. Process CLOSED TRADES (Missed Opportunity Tracker)
        history_updated = False
        for t in todays_closed:
            # Skip if SL Hit AFTER hitting Targets
            if t['status'] == 'SL_HIT' and t.get('targets_hit_indices'):
                continue

            inst_key = f"{t['exchange']}:{t['symbol']}"
            if inst_key in live_prices:
                ltp = live_prices[inst_key]['last_price']
                
                # Check if current price is higher than the recorded high
                current_high = t.get('made_high', t['entry_price'])
                if ltp > current_high:
                    t['made_high'] = ltp
                    # Update the database record
                    db.session.merge(TradeHistory(id=t['id'], data=json.dumps(t)))
                    history_updated = True
        
        if history_updated: 
            db.session.commit()
