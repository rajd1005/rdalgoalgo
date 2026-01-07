import pandas as pd
from datetime import datetime, timedelta

# Global Cache
instrument_dump = None 

def fetch_instruments(kite):
    global instrument_dump
    if instrument_dump is not None: return

    print("📥 Downloading Instrument List...")
    try:
        instrument_dump = pd.DataFrame(kite.instruments())
        instrument_dump['expiry_str'] = pd.to_datetime(instrument_dump['expiry']).dt.strftime('%Y-%m-%d')
        instrument_dump['expiry_date'] = pd.to_datetime(instrument_dump['expiry']).dt.date
        print("✅ Instruments Downloaded.")
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
    u = common_name.upper()
    if u in ["BANKNIFTY", "NIFTY BANK"]: return "BANKNIFTY"
    if u in ["NIFTY", "NIFTY 50"]: return "NIFTY"
    if u == "SENSEX": return "SENSEX"
    if "BANK" in u and "NIFTY" in u: return "BANKNIFTY"
    return u

def search_symbols(keyword):
    global instrument_dump
    if instrument_dump is None: return []
    keyword = keyword.upper()
    mask = (
        ((instrument_dump['segment'] == 'NFO-FUT') | (instrument_dump['segment'] == 'NSE')) & 
        (instrument_dump['name'].str.startswith(keyword))
    )
    return instrument_dump[mask]['name'].unique().tolist()[:10]

def get_symbol_details(kite, symbol):
    global instrument_dump
    if instrument_dump is None: fetch_instruments(kite)
    if instrument_dump is None: return {}
    
    clean = get_zerodha_symbol(symbol)
    today = datetime.now().date()
    
    # Lot Size from Futures
    lot = 1
    futs = instrument_dump[(instrument_dump['name'] == clean) & (instrument_dump['segment'] == 'NFO-FUT')]
    if not futs.empty: lot = int(futs.iloc[0]['lot_size'])
    
    # Expiries
    f_exp = sorted(futs[futs['expiry_date'] >= today]['expiry_str'].unique().tolist())
    opts = instrument_dump[(instrument_dump['name'] == clean) & (instrument_dump['instrument_type'] == 'CE')]
    o_exp = sorted(opts[opts['expiry_date'] >= today]['expiry_str'].unique().tolist())
    
    return {"symbol": clean, "lot_size": lot, "fut_expiries": f_exp, "opt_expiries": o_exp}

def get_chain_data(symbol, expiry_date, option_type, ltp):
    global instrument_dump
    if instrument_dump is None: return []
    
    c = instrument_dump[
        (instrument_dump['name'] == symbol) & 
        (instrument_dump['expiry_str'] == expiry_date) & 
        (instrument_dump['instrument_type'] == option_type)
    ]
    if c.empty: return []
    
    strikes = sorted(c['strike'].unique().tolist())
    if not strikes: return []
    atm = min(strikes, key=lambda x: abs(x - ltp))
    
    res = []
    for s in strikes:
        lbl = "OTM"
        if s == atm: lbl = "🔴 ATM"
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

def fetch_historical_check(kite, symbol, expiry, strike, type_, timestamp_str):
    symbol = get_zerodha_symbol(symbol)
    ts = get_exact_symbol(symbol, expiry, strike, type_)
    if not ts: return {"status": "error", "message": "Symbol Not Found"}
    
    global instrument_dump
    if instrument_dump is None: return {"status": "error", "message": "System Loading"}
    
    token = instrument_dump[instrument_dump['tradingsymbol'] == ts].iloc[0]['instrument_token']
    try:
        qt = datetime.strptime(timestamp_str.replace("T", " "), "%Y-%m-%d %H:%M")
        d = kite.historical_data(token, qt, qt + timedelta(minutes=1), "minute")
        if d:
            c = d[0]
            c['date'] = c['date'].strftime('%Y-%m-%d %H:%M')
            return {"status": "success", "data": c, "symbol": ts}
        return {"status": "error", "message": "No Data"}
    except Exception as e: return {"status": "error", "message": str(e)}
