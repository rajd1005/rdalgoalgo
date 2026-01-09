import pandas as pd
from datetime import datetime, timedelta
import pytz

# Global IST Timezone
IST = pytz.timezone('Asia/Kolkata')

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
    except:
        return {"NIFTY":0, "BANKNIFTY":0, "SENSEX":0}

def get_zerodha_symbol(common_name):
    if not common_name: return ""
    
    # NEW: Handle "SYMBOL (EXCHANGE) : LTP" format
    # Example: "RELIANCE (NSE) : 2500.0" -> "RELIANCE"
    cleaned = common_name
    if "(" in cleaned:
        cleaned = cleaned.split("(")[0]
    
    u = cleaned.upper().strip()
    
    if u in ["BANKNIFTY", "NIFTY BANK", "BANK NIFTY"]: return "BANKNIFTY"
    if u in ["NIFTY", "NIFTY 50", "NIFTY50"]: return "NIFTY"
    if u == "SENSEX": return "SENSEX"
    if u == "FINNIFTY": return "FINNIFTY"
    return u

# Updated to accept kite and fetch LTPs
def search_symbols(kite, keyword):
    global instrument_dump
    if instrument_dump is None: return []
    k = keyword.upper()
    
    # Filter by 'exchange' to capture ALL segments
    valid_exchanges = ['NSE', 'NFO', 'MCX', 'CDS', 'BSE', 'BFO']
    
    mask = (instrument_dump['exchange'].isin(valid_exchanges)) & (instrument_dump['name'].str.startswith(k))
    
    # Get unique combinations of Name and Exchange
    matches = instrument_dump[mask].drop_duplicates(subset=['name', 'exchange']).head(10)
    
    results = []
    
    for _, row in matches.iterrows():
        # Fetch Details (LTP) for each result
        # We pass the specific exchange to get the correct price (NSE vs BSE vs MCX)
        details = get_symbol_details(kite, row['name'], preferred_exchange=row['exchange'])
        ltp = details.get('ltp', 0)
        
        # Format: "SYMBOL (EXCHANGE) : LTP"
        display_str = f"{row['name']} ({row['exchange']}) : {ltp}"
        results.append(display_str)
        
    return results

def adjust_cds_lot_size(symbol, lot_size):
    s = symbol.upper()
    if lot_size == 1:
        if "JPYINR" in s:
            return 100000
        if any(x in s for x in ["USDINR", "EURINR", "GBPINR", "USDJPY", "EURUSD", "GBPUSD"]):
            return 1000
    return lot_size

def get_symbol_details(kite, symbol, preferred_exchange=None):
    global instrument_dump
    if instrument_dump is None: fetch_instruments(kite)
    if instrument_dump is None: return {}
    
    clean = get_zerodha_symbol(symbol)
    today = datetime.now(IST).date()
    
    # 1. Determine Exchange & Fetch LTP (Spot/Future)
    ltp = 0
    exchange_to_use = "NSE"
    
    rows = instrument_dump[instrument_dump['name'] == clean]
    
    if not rows.empty:
        exchanges = rows['exchange'].unique().tolist()
        
        # Use preferred exchange if available and valid
        if preferred_exchange and preferred_exchange in exchanges:
            exchange_to_use = preferred_exchange
        else:
            # Default Priority
            if 'MCX' in exchanges: exchange_to_use = 'MCX'
            elif 'CDS' in exchanges: exchange_to_use = 'CDS'
            elif 'BFO' in exchanges: exchange_to_use = 'BSE' 
            elif 'NFO' in exchanges: exchange_to_use = 'NSE'
            elif 'BSE' in exchanges: exchange_to_use = 'BSE'
    
    quote_sym = f"{exchange_to_use}:{clean}"
    if clean == "NIFTY": quote_sym = "NSE:NIFTY 50"
    if clean == "BANKNIFTY": quote_sym = "NSE:NIFTY BANK"
    if clean == "SENSEX": quote_sym = "BSE:SENSEX"
    
    try:
        q = kite.quote(quote_sym)
        if quote_sym in q:
            ltp = q[quote_sym]['last_price']
    except:
        ltp = 0
        
    # Fallback: If Spot LTP is 0 (or not found), fetch Near Future LTP
    # This is common for MCX/CDS where 'Spot' isn't easily quotable
    if ltp == 0 and not rows.empty:
        try:
            # If we are looking for MCX, we must look at MCX Futures
            # If we are looking for NFO (but failed to get Spot), look at NFO Futures
            target_exch = exchange_to_use if exchange_to_use in ['MCX', 'CDS'] else 'NFO'
            if preferred_exchange in ['MCX', 'CDS']: target_exch = preferred_exchange

            futs_all = rows[(rows['instrument_type'] == 'FUT') & (rows['expiry_date'] >= today)]
            
            # Filter by exchange if needed to avoid mixing NSE/BSE futures if any
            if exchange_to_use in ['MCX', 'CDS']:
                futs_all = futs_all[futs_all['exchange'] == exchange_to_use]

            if not futs_all.empty:
                futs_all = futs_all.sort_values('expiry_date')
                near_fut = futs_all.iloc[0]
                fut_sym = f"{near_fut['exchange']}:{near_fut['tradingsymbol']}"
                ltp = kite.quote(fut_sym)[fut_sym]['last_price']
        except:
            pass

    # 2. Get Lot Size
    lot = 1
    priority_exchanges = ['MCX', 'CDS', 'BFO', 'NFO']
    found_lot = False
    used_exchange = ""
    
    for ex in priority_exchanges:
        futs = rows[(rows['exchange'] == ex) & (rows['instrument_type'] == 'FUT')]
        if not futs.empty:
            lot = int(futs.iloc[0]['lot_size'])
            used_exchange = ex
            found_lot = True
            break
            
    if not found_lot:
        for ex in priority_exchanges:
            opts = rows[(rows['exchange'] == ex) & (rows['instrument_type'].isin(['CE', 'PE']))]
            if not opts.empty:
                lot = int(opts.iloc[0]['lot_size'])
                used_exchange = ex
                found_lot = True
                break
    
    if used_exchange == 'CDS':
        lot = adjust_cds_lot_size(clean, lot)

    # 3. Get Expiries
    f_exp = sorted(rows[(rows['instrument_type'] == 'FUT') & (rows['expiry_date'] >= today)]['expiry_str'].unique().tolist())
    o_exp = sorted(rows[(rows['instrument_type'].isin(['CE', 'PE'])) & (rows['expiry_date'] >= today)]['expiry_str'].unique().tolist())
    
    return {
        "symbol": clean, 
        "ltp": ltp,
        "lot_size": lot, 
        "fut_expiries": f_exp, 
        "opt_expiries": o_exp
    }

def get_chain_data(symbol, expiry_date, option_type, ltp):
    global instrument_dump
    if instrument_dump is None: return []
    
    clean_symbol = get_zerodha_symbol(symbol)
    
    c = instrument_dump[(instrument_dump['name'] == clean_symbol) & (instrument_dump['expiry_str'] == expiry_date) & (instrument_dump['instrument_type'] == option_type)]
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
    
    clean_symbol = get_zerodha_symbol(symbol)
    
    if option_type == "FUT":
        mask = (instrument_dump['name'] == clean_symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['instrument_type'] == "FUT")
    else:
        if not strike or str(strike).strip().lower() == 'null': 
            return None
        try:
            strike_price = float(strike)
        except ValueError:
            return None

        mask = (instrument_dump['name'] == clean_symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['strike'] == strike_price) & (instrument_dump['instrument_type'] == option_type)
        
    if not mask.any(): return None
    return instrument_dump[mask].iloc[0]['tradingsymbol']

def get_specific_ltp(kite, symbol, expiry, strike, inst_type):
    ts = get_exact_symbol(symbol, expiry, strike, inst_type)
    if not ts: return 0
    try:
        global instrument_dump
        exch = "NFO" 
        if instrument_dump is not None:
             row = instrument_dump[instrument_dump['tradingsymbol'] == ts]
             if not row.empty:
                 exch = row.iloc[0]['exchange']
        
        return kite.quote(f"{exch}:{ts}")[f"{exch}:{ts}"]['last_price']
    except:
        return 0

def simulate_trade(kite, symbol, expiry, strike, type_, time_str, sl_points, custom_entry, custom_targets, quantity=1):
    symbol_common = get_zerodha_symbol(symbol)
    tradingsymbol = get_exact_symbol(symbol_common, expiry, strike, type_)
    if not tradingsymbol:
        return {"status": "error", "message": "Symbol Not Found"}
    
    global instrument_dump
    token_row = instrument_dump[instrument_dump['tradingsymbol'] == tradingsymbol]
    if token_row.empty:
        return {"status": "error", "message": "Token Not Found"}
    token = token_row.iloc[0]['instrument_token']
    
    try:
        start_dt = datetime.strptime(time_str.replace("T", " "), "%Y-%m-%d %H:%M")
        end_dt = datetime.now(IST) + timedelta(days=1)
        
        candles = kite.historical_data(token, start_dt, end_dt, "minute")
        
        if not candles:
            return {"status": "error", "message": "No Data Found"}
            
        first = candles[0]
        
        is_limit_order = (float(custom_entry) > 0)
        entry = float(custom_entry) if is_limit_order else first['open']
        
        if len(custom_targets) == 3 and custom_targets[0] > 0:
            tgts = custom_targets
        else:
            tgts = [entry+sl_points*0.5, entry+sl_points*1.0, entry+sl_points*2.0]
        
        sl = entry - sl_points
        status = "PENDING" if is_limit_order else "OPEN"
        exit_p = 0
        exit_t = ""
        
        logs = [f"[{time_str}] Trade Added/Setup"]
        
        trade_active = False
        if not is_limit_order:
            trade_active = True
            logs.append(f"[{first['date']}] Trade Activated/Entered @ {entry} | P/L ₹ 0.00")
            
        targets_hit_indices = [] 
        made_high = entry
        
        for c in candles:
            curr_high = c['high']
            curr_low = c['low']
            c_time = str(c['date']) 
            
            if not trade_active and status == "PENDING":
                if curr_low <= entry <= curr_high:
                    status = "OPEN"
                    trade_active = True
                    logs.append(f"[{c_time}] Trade Activated/Entered @ {entry} | P/L ₹ 0.00")
                    made_high = entry 
                else:
                    continue 
            
            if status != "PENDING":
                if curr_high > made_high:
                    made_high = curr_high
            
            if status == "OPEN":
                if curr_low <= sl:
                    loss_amt = (sl - entry) * quantity
                    if sl >= entry:
                        status = "COST_EXIT"
                        logs.append(f"[{c_time}] Price returned to Entry (Cost) @ {sl} | P/L ₹ {loss_amt:.2f}")
                    else:
                        status = "SL_HIT"
                        logs.append(f"[{c_time}] SL Hit @ {sl} | P/L ₹ {loss_amt:.2f}")
                    exit_p = sl
                    exit_t = c_time
                    
                elif status == "OPEN":
                    for i, t_price in enumerate(tgts):
                        if i not in targets_hit_indices and curr_high >= t_price:
                            targets_hit_indices.append(i)
                            gain_amt = (t_price - entry) * quantity
                            logs.append(f"[{c_time}] Target {i+1} Hit @ {t_price} | P/L ₹ {gain_amt:.2f}")
                            if i == len(tgts) - 1:
                                status = "TARGET_HIT"
                                exit_p = t_price
                                exit_t = c_time
                                logs.append(f"[{c_time}] Final Target Hit @ {t_price} | P/L ₹ {gain_amt:.2f}")

        profit_pts = made_high - entry
        profit_amt = profit_pts * quantity
        if status == "PENDING":
             logs.append("Trade Never Triggered")
             made_high = 0
             profit_amt = 0
        
        logs.append(f"Made High: {made_high} (Max Potential Profit: ₹ {profit_amt:.2f})")

        active = (status == "OPEN")
        ltp = candles[-1]['close'] if active else exit_p
        
        return {
            "status": "success", "is_active": active,
            "trade_data": {
                "symbol": tradingsymbol, "entry_price": entry, "current_ltp": ltp,
                "sl": sl, "targets": tgts, "status": status, "exit_price": exit_p,
                "exit_time": exit_t, "logs": logs, "quantity": 0, "made_high": made_high
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
