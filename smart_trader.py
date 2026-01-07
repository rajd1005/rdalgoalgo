import pandas as pd
from datetime import datetime

# Global cache
instrument_dump = None 

def fetch_instruments(kite):
    global instrument_dump
    if instrument_dump is not None:
        return

    print("📥 Downloading Instrument List (Master Dump)...")
    try:
        instrument_dump = pd.DataFrame(kite.instruments("NFO"))
        instrument_dump['expiry'] = pd.to_datetime(instrument_dump['expiry']).dt.date
        print("✅ Instruments Downloaded & Parsed.")
    except Exception as e:
        print(f"❌ Failed to fetch instruments: {e}")

def get_atm_strike(ltp, step=50):
    return round(ltp / step) * step

def search_symbols(keyword):
    """Returns a list of unique trading symbols matching the keyword"""
    global instrument_dump
    if instrument_dump is None:
        return []
    
    keyword = keyword.upper()
    # Filter unique names that start with the keyword (e.g., "INFY")
    # We filter for FUTURES to get the underlying names easily
    mask = (instrument_dump['segment'] == 'NFO-FUT') & (instrument_dump['name'].str.startswith(keyword))
    unique_names = instrument_dump[mask]['name'].unique().tolist()
    return unique_names[:10] # Return top 10 matches

def get_matrix_data(kite, symbol):
    """
    Returns: { "ltp": 24000, "atm": 24000, "strikes": [23000, ... 25000] }
    """
    global instrument_dump
    if instrument_dump is None:
        fetch_instruments(kite)

    # 1. Get LTP (Spot Price)
    try:
        # Try fetching spot from NSE (e.g., NSE:RELIANCE)
        quote_symbol = f"NSE:{symbol}"
        if symbol in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
            # Index symbols map differently
            idx_map = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK", "FINNIFTY": "NIFTY FIN SERVICE"}
            quote_symbol = f"NSE:{idx_map.get(symbol, symbol)}"

        quote = kite.quote(quote_symbol)
        ltp = quote[quote_symbol]['last_price']
    except:
        print(f"⚠️ Could not fetch LTP for {symbol}. Using Dummy.")
        ltp = 24200 if "NIFTY" in symbol else 1000 # Dummy Fallback

    # 2. Determine Step Size (Index vs Stock)
    step = 100 if "BANK" in symbol else 50
    # For stocks, step sizes vary (e.g. 5, 10, 20). 
    # Logic: Get all available strikes for this expiry and find the closest ones.

    # 3. Filter Option Chain for Nearest Expiry
    today = datetime.now().date()
    
    # Get all options for this symbol
    opts = instrument_dump[
        (instrument_dump['name'] == symbol) & 
        (instrument_dump['instrument_type'] == 'CE') & # Just need strikes, type doesn't matter
        (instrument_dump['expiry'] >= today)
    ]
    
    if opts.empty:
        return {"ltp": ltp, "atm": 0, "strikes": []}

    # Find nearest expiry
    nearest_expiry = opts.sort_values('expiry').iloc[0]['expiry']
    
    # Get all strikes for this expiry
    expiry_opts = opts[opts['expiry'] == nearest_expiry]
    all_strikes = sorted(expiry_opts['strike'].unique().tolist())

    # 4. Find ATM (Closest Strike to LTP)
    atm_strike = min(all_strikes, key=lambda x: abs(x - ltp))

    # 5. Return a slice of strikes (e.g., 10 above and 10 below ATM)
    try:
        atm_index = all_strikes.index(atm_strike)
        start = max(0, atm_index - 10)
        end = min(len(all_strikes), atm_index + 11)
        relevant_strikes = all_strikes[start:end]
    except:
        relevant_strikes = all_strikes[:20]

    return {
        "ltp": ltp,
        "atm": atm_strike,
        "strikes": relevant_strikes
    }

def get_exact_symbol(symbol, strike, option_type):
    """Reconstructs the specific trading symbol"""
    global instrument_dump
    today = datetime.now().date()
    
    relevant = instrument_dump[
        (instrument_dump['name'] == symbol) &
        (instrument_dump['strike'] == float(strike)) &
        (instrument_dump['instrument_type'] == option_type) &
        (instrument_dump['expiry'] >= today)
    ]
    
    if relevant.empty: return None
    return relevant.sort_values('expiry').iloc[0]['tradingsymbol']
