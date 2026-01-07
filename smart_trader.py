import pandas as pd
from datetime import datetime, timedelta

# Global cache
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

def get_zerodha_symbol(common_name):
    """
    Smart mapping that avoids confusing HDFCBANK with BANKNIFTY
    """
    upper = common_name.upper()
    
    # Strict matching for Indices
    if upper == "BANKNIFTY" or upper == "NIFTY BANK": return "BANKNIFTY"
    if upper == "NIFTY" or upper == "NIFTY 50": return "NIFTY"
    if upper == "FINNIFTY": return "FINNIFTY"
    
    # If user types "BANK", assume Index, but let specific stocks pass
    if "BANK" in upper and "NIFTY" in upper: return "BANKNIFTY"
    
    return upper

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
    
    clean_symbol = get_zerodha_symbol(symbol)
    today = datetime.now().date()

    # 1. Get LTP
    ltp = 0
    try:
        quote_sym = f"NSE:{clean_symbol}"
        if clean_symbol == "NIFTY": quote_sym = "NSE:NIFTY 50"
        if clean_symbol == "BANKNIFTY": quote_sym = "NSE:NIFTY BANK"
        ltp = kite.quote(quote_sym)[quote_sym]['last_price']
    except:
        ltp = 0

    # 2. Get Lot Size (Priority: Futures -> Equity)
    lot_size = 1
    futs = instrument_dump[(instrument_dump['name'] == clean_symbol) & (instrument_dump['segment'] == 'NFO-FUT')]
    
    if not futs.empty:
        lot_size = int(futs.iloc[0]['lot_size'])
    
    # 3. Expiries
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
    chain = instrument_dump[(instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry_date) & (instrument_dump['instrument_type'] == option_type)]
    if chain.empty: return []
    
    strikes = sorted(chain['strike'].unique().tolist())
    if not strikes: return []
    
    atm_strike = min(strikes, key=lambda x: abs(x - ltp))
    result = []
    for s in strikes:
        label = ""
        if s == atm_strike: label = "🔴 ATM"
        elif option_type == "CE": label = "ITM" if ltp > s else "OTM"
        elif option_type == "PE": label = "ITM" if ltp < s else "OTM"
        result.append({"strike": s, "label": label})
    return result

def get_specific_ltp(kite, symbol, expiry, strike, inst_type):
    global instrument_dump
    tradingsymbol, exchange = "", "NFO"
    
    if inst_type == "EQ":
        tradingsymbol = symbol
        exchange = "NSE"
    elif inst_type == "FUT":
        mask = (instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['instrument_type'] == "FUT")
        if mask.any(): tradingsymbol = instrument_dump[mask].iloc[0]['tradingsymbol']
    else:
        # Safety check for empty strike
        if not strike: return 0
        mask = (instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['strike'] == float(strike)) & (instrument_dump['instrument_type'] == inst_type)
        if mask.any(): tradingsymbol = instrument_dump[mask].iloc[0]['tradingsymbol']

    if not tradingsymbol: return 0
    try:
        key = f"{exchange}:{tradingsymbol}"
        return kite.quote(key)[key]['last_price']
    except:
        return 0

def get_exact_symbol(symbol, expiry, strike, option_type):
    global instrument_dump
    if option_type == "EQ": return symbol
    
    if option_type == "FUT":
        mask = (instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['instrument_type'] == "FUT")
    else:
        # CRITICAL FIX: Handle empty strike safely
        if not strike or strike == "":
            return None
            
        mask = (instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['strike'] == float(strike)) & (instrument_dump['instrument_type'] == option_type)
        
    if not mask.any(): return None
    return instrument_dump[mask].iloc[0]['tradingsymbol']

def fetch_historical_check(kite, symbol, expiry, strike, type_, timestamp_str):
    """
    Fetches the OHLC of a specific minute in the past.
    timestamp_str format: "2023-10-27 09:15"
    """
    # 1. Clean Symbol Name
    symbol = get_zerodha_symbol(symbol)
    
    # 2. Get Trading Symbol (with safe inputs)
    tradingsymbol = get_exact_symbol(symbol, expiry, strike, type_)
    
    if not tradingsymbol: 
        return {"status": "error", "message": f"Symbol Not Found (Check Expiry/Strike for {symbol})"}
    
    # 3. Get Token
    global instrument_dump
    token_row = instrument_dump[instrument_dump['tradingsymbol'] == tradingsymbol]
    if token_row.empty: return {"status": "error", "message": "Token Not Found"}
    token = token_row.iloc[0]['instrument_token']
    
    try:
        # 4. Fetch Data
        query_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M")
        # Fetch 1 minute candle
        data = kite.historical_data(token, query_time, query_time + timedelta(minutes=1), "minute")
        
        if data:
            # Format the date for JSON
            candle = data[0]
            if 'date' in candle:
                candle['date'] = candle['date'].strftime('%Y-%m-%d %H:%M:%S')
                
            return {"status": "success", "data": candle, "symbol": tradingsymbol}
        else:
            return {"status": "error", "message": "No Data Found for this Time"}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}
