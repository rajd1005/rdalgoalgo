import pandas as pd
from datetime import datetime, timedelta

# Global Instrument Cache
instrument_dump = None 

def fetch_instruments(kite):
    global instrument_dump
    if instrument_dump is not None: return

    print("📥 Downloading Instrument List (Please Wait)...")
    try:
        instrument_dump = pd.DataFrame(kite.instruments())
        # Convert expiry to string for JSON and date object for logic
        instrument_dump['expiry_str'] = pd.to_datetime(instrument_dump['expiry']).dt.strftime('%Y-%m-%d')
        instrument_dump['expiry_date'] = pd.to_datetime(instrument_dump['expiry']).dt.date
        print("✅ Instruments Downloaded Successfully.")
    except Exception as e:
        print(f"❌ Failed to fetch instruments: {e}")

def get_indices_ltp(kite):
    """Fetches Live Spot Prices"""
    try:
        # Fetching NIFTY 50, NIFTY BANK, SENSEX
        tokens = ["NSE:NIFTY 50", "NSE:NIFTY BANK", "BSE:SENSEX"]
        quotes = kite.quote(tokens)
        return {
            "NIFTY": quotes.get("NSE:NIFTY 50", {}).get('last_price', 0),
            "BANKNIFTY": quotes.get("NSE:NIFTY BANK", {}).get('last_price', 0),
            "SENSEX": quotes.get("BSE:SENSEX", {}).get('last_price', 0)
        }
    except:
        return {"NIFTY": 0, "BANKNIFTY": 0, "SENSEX": 0}

def get_zerodha_symbol(common_name):
    """
    Prevents mapping HDFCBANK -> BANKNIFTY.
    Only maps strictly Index names.
    """
    if not common_name: return ""
    upper = common_name.upper().strip()
    
    # Precise Index Mapping
    if upper in ["BANKNIFTY", "NIFTY BANK", "BANK NIFTY"]: return "BANKNIFTY"
    if upper in ["NIFTY", "NIFTY 50", "NIFTY50"]: return "NIFTY"
    if upper == "SENSEX": return "SENSEX"
    if upper == "FINNIFTY": return "FINNIFTY"
    
    return upper

def search_symbols(keyword):
    global instrument_dump
    if instrument_dump is None: return []
    
    keyword = keyword.upper()
    # Search in Futures (NFO) & Stocks (NSE)
    mask = (
        ((instrument_dump['segment'] == 'NFO-FUT') | (instrument_dump['segment'] == 'NSE')) & 
        (instrument_dump['name'].str.startswith(keyword))
    )
    return instrument_dump[mask]['name'].unique().tolist()[:10]

def get_symbol_details(kite, symbol):
    global instrument_dump
    if instrument_dump is None: fetch_instruments(kite)
    
    clean_symbol = get_zerodha_symbol(symbol)
    today = datetime.now().date()

    # 1. Get LTP (Spot Price)
    ltp = 0
    try:
        quote_sym = f"NSE:{clean_symbol}"
        if clean_symbol == "NIFTY": quote_sym = "NSE:NIFTY 50"
        if clean_symbol == "BANKNIFTY": quote_sym = "NSE:NIFTY BANK"
        if clean_symbol == "SENSEX": quote_sym = "BSE:SENSEX"
        
        ltp = kite.quote(quote_sym)[quote_sym]['last_price']
    except:
        ltp = 0

    # 2. Get Lot Size & Expiries
    lot_size = 1
    # Check Futures for Lot Size first
    futs = instrument_dump[(instrument_dump['name'] == clean_symbol) & (instrument_dump['segment'] == 'NFO-FUT')]
    
    if not futs.empty:
        lot_size = int(futs.iloc[0]['lot_size'])
    
    # Expiries
    fut_exps = sorted(futs[futs['expiry_date'] >= today]['expiry_str'].unique().tolist())
    
    opts = instrument_dump[(instrument_dump['name'] == clean_symbol) & (instrument_dump['instrument_type'] == 'CE')]
    opt_exps = sorted(opts[opts['expiry_date'] >= today]['expiry_str'].unique().tolist())

    return {
        "symbol": clean_symbol,
        "ltp": ltp,
        "lot_size": lot_size,
        "fut_expiries": fut_exps,
        "opt_expiries": opt_exps
    }

def get_chain_data(symbol, expiry_date, option_type, ltp):
    global instrument_dump
    if instrument_dump is None or not symbol or not expiry_date: return []

    chain = instrument_dump[
        (instrument_dump['name'] == symbol) & 
        (instrument_dump['expiry_str'] == expiry_date) & 
        (instrument_dump['instrument_type'] == option_type)
    ]
    
    if chain.empty: return []
    strikes = sorted(chain['strike'].unique().tolist())
    
    if not strikes: return []
    
    # Calculate ATM
    atm_strike = min(strikes, key=lambda x: abs(x - ltp))
    
    result = []
    for s in strikes:
        label = "OTM"
        if s == atm_strike:
            label = "ATM" # Logic handled in UI for color
        elif option_type == "CE":
            label = "ITM" if ltp > s else "OTM"
        elif option_type == "PE":
            label = "ITM" if ltp < s else "OTM"
            
        result.append({"strike": s, "label": label})
    return result

def get_exact_symbol(symbol, expiry, strike, option_type):
    global instrument_dump
    if instrument_dump is None: return None

    # Equity
    if option_type == "EQ": return symbol
    
    # Futures
    if option_type == "FUT":
        mask = (instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['instrument_type'] == "FUT")
    # Options
    else:
        if not strike: return None
        mask = (instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['strike'] == float(strike)) & (instrument_dump['instrument_type'] == option_type)
        
    if not mask.any(): return None
    return instrument_dump[mask].iloc[0]['tradingsymbol']

def get_specific_ltp(kite, symbol, expiry, strike, inst_type):
    tradingsymbol = get_exact_symbol(symbol, expiry, strike, inst_type)
    if not tradingsymbol: return 0
    try:
        # Determine Exchange
        exch = "NSE" if inst_type == "EQ" else "NFO"
        key = f"{exch}:{tradingsymbol}"
        return kite.quote(key)[key]['last_price']
    except:
        return 0

def fetch_historical_check(kite, symbol, expiry, strike, type_, timestamp_str):
    symbol = get_zerodha_symbol(symbol)
    tradingsymbol = get_exact_symbol(symbol, expiry, strike, type_)
    
    if not tradingsymbol: return {"status": "error", "message": "Symbol Not Found"}
    
    global instrument_dump
    token_row = instrument_dump[instrument_dump['tradingsymbol'] == tradingsymbol]
    if token_row.empty: return {"status": "error", "message": "Token Not Found"}
    token = token_row.iloc[0]['instrument_token']
    
    try:
        # Parse Time (Handle 'T' from HTML input)
        query_time = datetime.strptime(timestamp_str.replace("T", " "), "%Y-%m-%d %H:%M")
        data = kite.historical_data(token, query_time, query_time + timedelta(minutes=1), "minute")
        
        if data:
            candle = data[0]
            candle['date'] = candle['date'].strftime('%Y-%m-%d %H:%M')
            return {"status": "success", "data": candle, "symbol": tradingsymbol}
        return {"status": "error", "message": "No Data Found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
