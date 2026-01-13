import json
import time
from datetime import datetime, timedelta
import pandas as pd
import pytz
from database import db, ActiveTrade, TradeHistory
import smart_trader 
import settings

IST = pytz.timezone('Asia/Kolkata')

# Global State for Profit Trailing
GLOBAL_RISK_STATE = {
    'LIVE': {'high_pnl': float('-inf'), 'global_sl': float('-inf'), 'active': False},
    'PAPER': {'high_pnl': float('-inf'), 'global_sl': float('-inf'), 'active': False}
}

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


def update_trade_protection(kite, trade_id, sl, targets, trailing_sl=0, entry_price=None, target_controls=None, sl_to_entry=0, exit_multiplier=1):
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
                    new_controls.append({'enabled': True, 'lots': int(lots_here)})
                
                while len(new_targets) < 3: new_targets.append(0); new_controls.append({'enabled': False, 'lots': 0})
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

def get_time_str(custom_dt=None): 
    if custom_dt: return custom_dt.strftime("%Y-%m-%d %H:%M:%S")
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

def log_event(trade, message, timestamp=None):
    if 'logs' not in trade: trade['logs'] = []
    ts = timestamp if timestamp else get_time_str()
    trade['logs'].append(f"[{ts}] {message}")

def move_to_history(trade, final_status, exit_price, exit_time_str=None):
    real_pnl = 0
    was_active = trade['status'] != 'PENDING'
    if was_active:
        real_pnl = round((exit_price - trade['entry_price']) * trade['quantity'], 2)
    trade['pnl'] = real_pnl if was_active else 0
    trade['status'] = final_status; trade['exit_price'] = exit_price
    trade['exit_time'] = exit_time_str if exit_time_str else get_time_str()
    trade['exit_type'] = final_status
    
    # Remove heavy replay data before saving to history
    if 'replay_data' in trade: del trade['replay_data']

    if "Closed:" not in str(trade['logs']):
         log_event(trade, f"Closed: {final_status} @ {exit_price} | P/L ₹ {real_pnl:.2f}", timestamp=trade.get('last_update_time'))
    
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
    now = datetime.now(IST)
    exit_time_str = mode_settings.get('universal_exit_time', "15:25")
    try:
        exit_dt = datetime.strptime(exit_time_str, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
        exit_dt = IST.localize(exit_dt.replace(tzinfo=None))
        if now >= exit_dt and (now - exit_dt).seconds < 120:
             trades = load_trades()
             active_mode = [t for t in trades if t['mode'] == mode and not t.get('is_replay')]
             if active_mode:
                 for t in active_mode:
                     if t['mode'] == "LIVE" and t['status'] != 'PENDING':
                        manage_broker_sl(kite, t, cancel_completely=True)
                        try: kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                        except: pass
                     move_to_history(t, "TIME_EXIT", t.get('current_ltp', 0))
                 remaining = [t for t in trades if t['mode'] != mode or t.get('is_replay')]
                 save_trades(remaining)
                 return
    except Exception as e: print(f"Time Check Error: {e}")

    # Profit Lock (Global) - Skipped for Replay
    pnl_start = float(mode_settings.get('profit_lock', 0))
    if pnl_start > 0:
        current_total_pnl = get_day_pnl(mode)
        state = GLOBAL_RISK_STATE[mode]
        if not state['active'] and current_total_pnl >= pnl_start:
            state['active'] = True; state['high_pnl'] = current_total_pnl; state['global_sl'] = float(mode_settings.get('profit_min', 0))
        if state['active']:
            if current_total_pnl > state['high_pnl']:
                diff = current_total_pnl - state['high_pnl']
                trail_step = float(mode_settings.get('profit_trail', 0))
                if trail_step > 0 and diff >= trail_step:
                     steps = int(diff / trail_step)
                     state['global_sl'] += (steps * trail_step)
                     state['high_pnl'] = current_total_pnl
            if current_total_pnl <= state['global_sl']:
                trades = load_trades()
                active_mode = [t for t in trades if t['mode'] == mode and not t.get('is_replay')]
                for t in active_mode:
                     if t['mode'] == "LIVE" and t['status'] != 'PENDING':
                        manage_broker_sl(kite, t, cancel_completely=True)
                        try: kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                        except: pass
                     move_to_history(t, "PROFIT_LOCK", t.get('current_ltp', 0))
                remaining = [t for t in trades if t['mode'] != mode or t.get('is_replay')]
                save_trades(remaining)
                state['active'] = False

def can_place_order(mode):
    current_settings = settings.load_settings()
    mode_conf = current_settings['modes'][mode]
    max_loss_limit = float(mode_conf.get('max_loss', 0))
    if max_loss_limit > 0:
        limit = -abs(max_loss_limit)
        current_pnl = get_day_pnl(mode)
        if current_pnl <= limit: return False, f"Max Daily Loss Reached ({current_pnl:.2f} <= {limit})"
    return True, "OK"

def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points, custom_targets, order_type, limit_price=0, target_controls=None, trailing_sl=0, sl_to_entry=0, exit_multiplayer=1):
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
    if not target_controls: target_controls = [{'enabled': True, 'lots': 0}, {'enabled': True, 'lots': 0}, {'enabled': True, 'lots': 1000}]
    
    lot_size = smart_trader.get_lot_size(specific_symbol)
    final_trailing_sl = float(trailing_sl) if trailing_sl else 0
    if final_trailing_sl == -1.0: final_trailing_sl = float(sl_points)

    if exit_multiplayer > 1:
        final_goal = max([x for x in custom_targets if x > 0]) if [x for x in custom_targets if x > 0] else (entry_price + (sl_points * 2))
        dist = final_goal - entry_price; new_targets = []; new_controls = []
        base_lots = (quantity // lot_size) // exit_multiplayer
        rem = (quantity // lot_size) % exit_multiplayer
        for i in range(1, exit_multiplayer + 1):
            t_price = entry_price + (dist * (i / exit_multiplayer))
            new_targets.append(round(t_price, 2))
            new_controls.append({'enabled': True, 'lots': int(base_lots + (rem if i == exit_multiplayer else 0))})
        while len(new_targets) < 3: new_targets.append(0); new_controls.append({'enabled': False, 'lots': 0})
        targets = new_targets; target_controls = new_controls

    logs.insert(0, f"[{get_time_str()}] Trade Added. Status: {status}")
    record = {
        "id": int(time.time()), "entry_time": get_time_str(), "symbol": specific_symbol, "exchange": exchange,
        "mode": mode, "order_type": order_type, "status": status, "entry_price": entry_price, "quantity": quantity,
        "sl": entry_price - sl_points, "targets": targets, "target_controls": target_controls,
        "lot_size": lot_size, "trailing_sl": final_trailing_sl, "sl_to_entry": int(sl_to_entry),
        "exit_multiplier": int(exit_multiplayer), "sl_order_id": sl_order_id,
        "targets_hit_indices": [], "highest_ltp": entry_price, "made_high": entry_price, "current_ltp": current_ltp, "trigger_dir": trigger_dir, "logs": logs
    }
    trades.append(record)
    save_trades(trades)
    return {"status": "success", "trade": record}

# --- NEW: IMPORT REPLAY ENGINE (Streaming) ---
def import_past_trade(kite, symbol, entry_dt_str, qty, entry_price, sl_price, targets, trailing_sl, sl_to_entry, exit_multiplier, target_controls):
    try:
        entry_time = datetime.strptime(entry_dt_str, "%Y-%m-%dT%H:%M") 
        now = datetime.now()
        exchange = get_exchange(symbol)
        
        token = smart_trader.get_instrument_token(symbol, exchange)
        if not token: return {"status": "error", "message": "Symbol Token not found"}
        
        hist_data = smart_trader.fetch_historical_data(kite, token, entry_time, now, "minute")
        if not hist_data or len(hist_data) == 0: 
            return {"status": "error", "message": "No historical data found"}
        
        # Initialize Replay State
        logs = [f"[{entry_time.strftime('%Y-%m-%d %H:%M:%S')}] 🎬 Replay Started. Waiting for Trigger: {entry_price}"]
        
        # We start with the first candle price as LTP
        initial_ltp = hist_data[0]['open']

        record = {
            "id": int(time.time()), 
            "entry_time": entry_time.strftime("%Y-%m-%d %H:%M:%S"), 
            "last_update_time": entry_time.strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol, "exchange": exchange,
            "mode": "PAPER", 
            "is_replay": True,  # Flag to identify replay trades
            "replay_data": hist_data, # Store the full candle series
            "replay_index": 0,        # Pointer to current candle
            
            "order_type": "MARKET", "status": "PENDING", 
            "entry_price": entry_price, 
            "quantity": qty,
            "sl": float(sl_price), 
            "targets": [float(x) for x in targets], 
            "target_controls": target_controls,
            "lot_size": smart_trader.get_lot_size(symbol), 
            "trailing_sl": float(trailing_sl), "sl_to_entry": int(sl_to_entry), "exit_multiplier": int(exit_multiplier), 
            "sl_order_id": None,
            "targets_hit_indices": [], 
            "highest_ltp": entry_price, "made_high": entry_price, 
            "current_ltp": initial_ltp, "trigger_dir": "BELOW", 
            "logs": logs
        }
        
        trades = load_trades()
        trades.append(record)
        save_trades(trades)
        
        return {"status": "success", "message": f"Simulation Started. Watching {len(hist_data)} candles."}

    except Exception as e: return {"status": "error", "message": str(e)}

def process_replay_step(t):
    """ Advances the replay trade by one historical candle """
    data = t.get('replay_data', [])
    idx = t.get('replay_index', 0)
    
    if idx >= len(data):
        move_to_history(t, "TIME_EXIT", t.get('current_ltp', 0), t.get('last_update_time'))
        return True # Finished

    candle = data[idx]
    # Candle format: {'date': 'YYYY-MM-DD HH:MM:SS', 'open': ..., 'high': ..., 'low': ..., 'close': ...}
    
    c_time = candle['date']
    t['last_update_time'] = c_time
    
    open_p = candle['open']
    high = candle['high']
    low = candle['low']
    close = candle['close']
    
    # Update LTP for display (Use Close to represent end of this minute)
    t['current_ltp'] = close
    
    exit_triggered = False
    exit_reason = ""
    exit_price = close

    # 1. PENDING -> OPEN Logic
    if t['status'] == "PENDING":
        # Check if price touched entry within this candle
        if low <= t['entry_price'] <= high:
            t['status'] = "OPEN"
            t['highest_ltp'] = max(t['entry_price'], high)
            log_event(t, f"🚀 Triggered @ {t['entry_price']}", timestamp=c_time)
        elif idx == 0: # Force open on first candle if gap logic applies? (Optional, kept strict for now)
            pass

    # 2. OPEN Trade Logic (Risk Engine)
    elif t['status'] == "OPEN":
        t['highest_ltp'] = max(t.get('highest_ltp', 0), high)
        t['made_high'] = t['highest_ltp']

        # A. Trailing Logic (Step)
        if t.get('trailing_sl', 0) > 0:
            step = t['trailing_sl']
            current_sl = t['sl']
            # Trail based on High made in this candle
            diff = high - (current_sl + step)
            
            if diff >= step:
                steps_to_move = int(diff / step)
                new_sl = current_sl + (steps_to_move * step)
                
                # Apply Caps
                limit_val = float('inf')
                mode = int(t.get('sl_to_entry', 0))
                if mode == 1: limit_val = t['entry_price']
                elif mode == 2 and len(t['targets'])>0: limit_val = t['targets'][0]
                elif mode == 3 and len(t['targets'])>1: limit_val = t['targets'][1]
                
                if mode > 0: new_sl = min(new_sl, limit_val)
                
                if new_sl > current_sl:
                    t['sl'] = new_sl
                    log_event(t, f"📈 Trailing SL Moved: {current_sl:.2f} -> {new_sl:.2f} (High: {high})", timestamp=c_time)

        # B. Check SL (Low of candle)
        if low <= t['sl']:
            exit_triggered = True
            exit_reason = "SL_HIT"
            exit_price = t['sl']
        
        # C. Check Targets (High of candle)
        elif not exit_triggered:
            controls = t.get('target_controls', [{'enabled':True, 'lots':0}]*3)
            for i, tgt in enumerate(t['targets']):
                if i not in t.get('targets_hit_indices', []) and high >= tgt:
                    t.setdefault('targets_hit_indices', []).append(i)
                    conf = controls[i]
                    if not conf['enabled']: continue
                    
                    lot_size = t.get('lot_size') or 1
                    qty_to_exit = conf.get('lots', 0) * lot_size
                    
                    if qty_to_exit >= t['quantity']:
                        exit_triggered = True
                        exit_reason = "TARGET_HIT"
                        exit_price = tgt
                        break
                    elif qty_to_exit > 0:
                        t['quantity'] -= qty_to_exit
                        log_event(t, f"Target {i+1} Hit ({tgt}). Partial Exit {qty_to_exit}", timestamp=c_time)

    # Increment Index for next loop
    t['replay_index'] = idx + 1
    
    if exit_triggered:
        move_to_history(t, exit_reason, exit_price, c_time)
        return True # Trade Ended
        
    return False # Trade Continues

def promote_to_live(kite, trade_id):
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
    trades = load_trades()
    active_list = []; found = False
    for t in trades:
        if t['id'] == int(trade_id):
            found = True
            exit_p = t.get('current_ltp', 0)
            if not t.get('is_replay'):
                try: exit_p = kite.quote(f"{t['exchange']}:{t['symbol']}")[f"{t['exchange']}:{t['symbol']}"]['last_price']
                except: pass
            
            if t['mode'] == "LIVE" and t['status'] != "PENDING":
                manage_broker_sl(kite, t, cancel_completely=True)
                try: kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                except: pass
            move_to_history(t, "MANUAL_EXIT", exit_p, t.get('last_update_time'))
        else: active_list.append(t)
    if found: save_trades(active_list)
    return found

def update_risk_engine(kite):
    current_settings = settings.load_settings()
    
    # 1. Process Replay Trades (Simulated Step)
    active_trades = load_trades()
    if not active_trades: return
    
    replay_dirty = False
    active_replay = [t for t in active_trades if t.get('is_replay')]
    for t in active_replay:
        if process_replay_step(t):
            # Trade finished inside process_replay_step and moved to history
            # Remove from active_trades list for saving
            active_trades = [x for x in active_trades if x['id'] != t['id']]
        replay_dirty = True
        
    if replay_dirty: save_trades(active_trades)

    # 2. Process Live/Paper Trades (Realtime)
    active_real = [t for t in active_trades if not t.get('is_replay')]
    if not active_real: return

    check_global_exit_conditions(kite, "PAPER", current_settings['modes']['PAPER'])
    check_global_exit_conditions(kite, "LIVE", current_settings['modes']['LIVE'])

    instruments = list(set([f"{t['exchange']}:{t['symbol']}" for t in active_real]))
    try: live_prices = kite.quote(instruments)
    except: return

    active_list = []; updated = False
    
    # Reload in case Replay logic modified the list (though we separated them)
    # But safe to iterate active_real which is a subset
    for t in active_real:
        inst_key = f"{t['exchange']}:{t['symbol']}"
        if inst_key not in live_prices:
             active_list.append(t); continue
             
        ltp = live_prices[inst_key]['last_price']
        t['current_ltp'] = ltp; updated = True
        t['last_update_time'] = get_time_str()
        
        if t['status'] == "PENDING":
            if (t.get('trigger_dir') == 'BELOW' and ltp <= t['entry_price']) or (t.get('trigger_dir') == 'ABOVE' and ltp >= t['entry_price']):
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
    
    if updated: 
        # Re-merge Replay trades that are still active (since we only processed Active Real here)
        final_list = active_list + [x for x in load_trades() if x.get('is_replay')]
        save_trades(final_list)
