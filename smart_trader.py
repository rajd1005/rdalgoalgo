import pandas as pd
from datetime import datetime

# Global cache
instrument_dump = None 

def fetch_instruments(kite):
    global instrument_dump
    print("📥 Downloading Instrument List (Master Dump)...")
    try:
        instrument_dump = pd.DataFrame(kite.instruments("NFO"))
        instrument_dump['expiry'] = pd.to_datetime(instrument_dump['expiry']).dt.date
        print("✅ Instruments Downloaded & Parsed.")
    except Exception as e:
        print(f"❌ Failed to fetch instruments: {e}")

def get_atm_strike(ltp, step=50):
    """Rounds LTP to nearest strike price"""
    return round(ltp / step) * step

def get_zerodha_symbol(common_name):
    """
    MAPPING FIX: Converts 'NIFTY 50' -> 'NIFTY' for Zerodha compatibility
    """
    common_name = common_name.upper()
    if "BANK" in common_name:
        return "BANKNIFTY"
    elif "NIFTY" in common_name and "50" in common_name:
        return "NIFTY"
    elif "NIFTY" in common_name:
        return "NIFTY"
    return common_name

def find_option_symbol(kite, underlying="NIFTY", option_type="CE", ltp=None):
    global instrument_dump
    
    # 1. Download list if missing
    if instrument_dump is None:
        fetch_instruments(kite)

    # 2. Fix the Name Mismatch (The Logic Fix)
    search_name = get_zerodha_symbol(underlying)

    # 3. Handle Market Closed (Dummy Price Logic)
    if ltp is None:
        try:
            # Try to get live price of the INDEX (e.g. NIFTY 50)
            # Note: We must use the INDEX name here, not the Option name
            index_map = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK"}
            index_search = index_map.get(search_name, "NIFTY 50")
            
            quote = kite.quote(f"NSE:{index_search}")
            ltp = quote[f"NSE:{index_search}"]["last_price"]
        except:
            print("⚠️ Market Closed/Error. Using Dummy LTP: 24200")
            ltp = 24200 

    # 4. Calculate Strike
    # Note: BankNifty step is 100, Nifty is 50
    step = 100 if "BANK" in search_name else 50
    strike = get_atm_strike(ltp, step)
    
    print(f"🧐 Searching: {search_name} | Strike: {strike} | Type: {option_type}")

    # 5. Filter the Dataframe
    today = datetime.now().date()
    
    relevant = instrument_dump[
        (instrument_dump['name'] == search_name) &
        (instrument_dump['strike'] == strike) &
        (instrument_dump['instrument_type'] == option_type) &
        (instrument_dump['expiry'] >= today)
    ]
    
    if relevant.empty:
        # Debugging Help
        print(f"❌ ERROR: No contract found for {search_name} {strike} {option_type}")
        return None

    # 6. Sort and Pick Nearest Expiry
    contract = relevant.sort_values('expiry').iloc[0]
    
    return {
        "tradingsymbol": contract['tradingsymbol'],
        "instrument_token": int(contract['instrument_token']),
        "strike": contract['strike']
    }
