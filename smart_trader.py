import pandas as pd
from datetime import datetime, timedelta

# Global Instrument Cache
instrument_dump = None 

def fetch_instruments(kite):
    global instrument_dump
    if instrument_dump is not None: return

    print("📥 Downloading Instrument List...")
    try:
        instrument_dump = pd.DataFrame(kite.instruments())
        instrument_dump['expiry_str'] = pd.to_datetime(instrument_dump['expiry']).dt.strftime('%Y-%m-%d')
        instrument_dump['expiry_date'] = pd.to_datetime(instrument_dump['expiry']).dt.date
        print("✅ Instruments Downloaded Successfully.")
    except Exception as e:
        print(f"❌ Failed to fetch instruments: {e}")

def get_indices_ltp(kite):
    try:
        q = kite.quote(["NSE:NIFTY 50", "NSE:NIFTY BANK", "BSE:SENSEX"])
        return {
            "NIFTY": q.get("NSE:NIFTY 50", {}).get('last_price', 0),
            "BANKNIFTY": q.get("NSE:NIFTY BANK", {}).get('last_price', 0),
            "SENSEX": q.get("BSE:SENSEX", {}).get('last_price', 0)
        }
    except: return {"NIFTY":0, "BANKNIFTY":0, "SENSEX":0}

def get_zerodha_symbol(common_name):
    if not common_name: return ""
    u = common_name.upper().strip()
    if u in ["BANKNIFTY", "NIFTY BANK"]: return "BANKNIFTY"
    if u in ["NIFTY", "NIFTY 50"]: return "NIFTY"
    if u == "SENSEX": return "SENSEX"
    if "BANK" in u and "NIFTY" in u: return "BANKNIFTY"
    return u

def search_symbols(keyword):
    global instrument_dump
    if instrument_dump is None: return []
    k = keyword.upper()
    mask = ((instrument_dump['segment'] == 'NFO-FUT') | (instrument_dump['segment'] == 'NSE')) & (instrument_dump['name'].str.startswith(k))
    return instrument_dump[mask]['name'].unique().tolist()[:10]

def get_symbol_details(kite, symbol):
    global instrument_dump
    if instrument_dump is None: fetch_instruments(kite)
    if instrument_dump is None: return {}
    
    clean = get_zerodha_symbol(symbol)
    today = datetime.now().date()
    
    lot = 1
    futs = instrument_dump[(instrument_dump['name'] == clean) & (instrument_dump['segment'] == 'NFO-FUT')]
    if not futs.empty: lot = int(futs.iloc[0]['lot_size'])
    
    f_exp = sorted(futs[futs['expiry_date'] >= today]['expiry_str'].unique().tolist())
    opts = instrument_dump[(instrument_dump['name'] == clean) & (instrument_dump['instrument_type'] == 'CE')]
    o_exp = sorted(opts[opts['expiry_date'] >= today]['expiry_str'].unique().tolist())
    
    return {"symbol": clean, "lot_size": lot, "fut_expiries": f_exp, "opt_expiries": o_exp}

def get_chain_data(symbol, expiry_date, option_type, ltp):
    global instrument_dump
    if instrument_dump is None: return []
    
    c = instrument_dump[(instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry_date) & (instrument_dump['instrument_type'] == option_type)]
    if c.empty: return []
    
    strikes = sorted(c['strike'].unique().tolist())
    if not strikes: return []
    atm = min(strikes, key=lambda x: abs(x - ltp))
    
    res = []
    for s in strikes:
        lbl = "OTM"
        if s == atm: lbl = "ATM"
        elif option_type == "CE": lbl = "ITM" if ltp > s else "OTM"
        elif option_type == "PE": lbl = "ITM" if ltp < s else "OTM"
        res.append({"strike": s, "label": lbl})
    return res

def get_exact_symbol(symbol, expiry, strike, option_type):
    global instrument_dump
    if instrument_dump is None: return None
    if option_type == "EQ": return symbol
    
    if option_type == "FUT":
        mask = (instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['instrument_type'] == "FUT")
    else:
        if not strike: return None
        mask = (instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['strike'] == float(strike)) & (instrument_dump['instrument_type'] == option_type)
        
    if not mask.any(): return None
    return instrument_dump[mask].iloc[0]['tradingsymbol']

def get_specific_ltp(kite, symbol, expiry, strike, inst_type):
    ts = get_exact_symbol(symbol, expiry, strike, inst_type)
    if not ts: return 0
    try:
        exch = "NSE" if inst_type == "EQ" else "NFO"
        return kite.quote(f"{exch}:{ts}")[f"{exch}:{ts}"]['last_price']
    except: return 0

# --- UPDATED SIMULATION LOGIC ---
def simulate_trade(kite, symbol, expiry, strike, type_, time_str, sl_points, custom_entry, custom_targets):
    """
    Backtests a trade.
    FIX 1: End Date = Tomorrow (Avoids Timezone crashes).
    FIX 2: Uses custom entry and targets if provided.
    """
    symbol_common = get_zerodha_symbol(symbol)
    tradingsymbol = get_exact_symbol(symbol_common, expiry, strike, type_)
    
    if not tradingsymbol: return {"status": "error", "message": "Symbol Not Found"}
    
    global instrument_dump
    token_row = instrument_dump[instrument_dump['tradingsymbol'] == tradingsymbol]
    if token_row.empty: return {"status": "error", "message": "Token Not Found"}
    token = token_row.iloc[0]['instrument_token']
    
    try:
        # Time Handling
        start_dt = datetime.strptime(time_str.replace("T", " "), "%Y-%m-%d %H:%M")
        # FIX: Set end_dt to tomorrow to ensure it's always > start_dt (handles UTC/IST mismatch)
        end_dt = datetime.now() + timedelta(days=1)
        
        candles = kite.historical_data(token, start_dt, end_dt, "minute")
        
        if not candles:
            return {"status": "error", "message": "No historical data found for this time."}
            
        # 1. Determine Entry
        first_candle = candles[0]
        # Use custom entry if provided (>0), else Open Price
        entry_price = float(custom_entry) if custom_entry > 0 else first_candle['open']
        
        # 2. Determine Targets/SL
        current_sl = entry_price - sl_points
        
        # If custom targets provided (size 3), use them. Else Auto-Calc.
        if len(custom_targets) == 3 and custom_targets[0] > 0:
            targets = custom_targets
        else:
            targets = [
                entry_price + (sl_points * 0.5),
                entry_price + (sl_points * 1.0),
                entry_price + (sl_points * 2.0)
            ]
        
        # Simulation Loop
        status = "OPEN"
        exit_price = 0
        exit_time = ""
        logs = [f"Simulated Entry at {first_candle['date']} @ {entry_price}"]
        
        t1_hit = False
        
        for candle in candles:
            low = candle['low']
            high = candle['high']
            curr_time = candle['date'].strftime('%Y-%m-%d %H:%M:%S')
            
            # Check SL
            if low <= current_sl:
                status = "SL_HIT"
                exit_price = current_sl
                exit_time = curr_time
                logs.append(f"[{curr_time}] Stop Loss Hit @ {current_sl}")
                break
                
            # Check T1 (Safe Guard)
            if high >= targets[0] and not t1_hit:
                t1_hit = True
                current_sl = entry_price # Move SL to Cost
                logs.append(f"[{curr_time}] Target 1 Hit. SL Moved to Entry.")
                
            # Check Final Target (T3)
            if high >= targets[2]:
                status = "TARGET_HIT"
                exit_price = targets[2]
                exit_time = curr_time
                logs.append(f"[{curr_time}] Final Target Hit @ {targets[2]}")
                break
        
        is_active = (status == "OPEN")
        if is_active:
            current_ltp = candles[-1]['close']
            logs.append(f"Trade still ACTIVE. Current Price: {current_ltp}")
        else:
            current_ltp = exit_price

        return {
            "status": "success",
            "is_active": is_active,
            "trade_data": {
                "symbol": tradingsymbol,
                "entry_price": entry_price,
                "current_ltp": current_ltp,
                "sl": current_sl,
                "targets": targets,
                "status": status,
                "exit_price": exit_price,
                "exit_time": exit_time,
                "logs": logs,
                "quantity": 0 # Filled by caller
            }
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}
