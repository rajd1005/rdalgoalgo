import pandas as pd
from datetime import datetime, timedelta

# Global cache to prevent re-downloading every second
instrument_dump = None 

def fetch_instruments(kite):
    """Downloads the master instrument list from Zerodha"""
    global instrument_dump
    print("📥 Downloading Instrument List (Master Dump)...")
    instrument_dump = pd.DataFrame(kite.instruments("NFO"))
    
    # Convert expiry to date object for comparison
    instrument_dump['expiry'] = pd.to_datetime(instrument_dump['expiry']).dt.date
    print("✅ Instruments Downloaded & Parsed.")

def get_atm_strike(ltp, step=50):
    """Rounds LTP to nearest strike price"""
    return round(ltp / step) * step

def find_option_symbol(kite, underlying="NIFTY", option_type="CE", ltp=None):
    """
    Finds the specific trading symbol for the nearest expiry.
    """
    global instrument_dump
    
    # 1. Download list if we haven't yet
    if instrument_dump is None:
        fetch_instruments(kite)
        
    # 2. If LTP is not provided, fetch it (Only works during market hours)
    # Since market is closed, we will simulate or skip this if testing manually
    if ltp is None:
        try:
            # Token for NIFTY 50 is 256265
            quote = kite.quote("NSE:NIFTY 50")
            ltp = quote["NSE:NIFTY 50"]["last_price"]
        except:
            print("⚠️ Market Closed/Error fetching LTP. Using Dummy LTP: 24000")
            ltp = 24000 # Hardcoded for night testing
            
    # 3. Calculate ATM Strike
    strike = get_atm_strike(ltp)
    print(f"🧐 Searching for: {underlying} | Strike: {strike} | Type: {option_type}")

    # 4. Filter the Dump
    today = datetime.now().date()
    
    relevant = instrument_dump[
        (instrument_dump['name'] == underlying) &
        (instrument_dump['strike'] == strike) &
        (instrument_dump['instrument_type'] == option_type) &
        (instrument_dump['expiry'] >= today)
    ]
    
    if relevant.empty:
        print("❌ No matching option found!")
        return None

    # 5. Sort by nearest expiry and pick top result
    contract = relevant.sort_values('expiry').iloc[0]
    
    print(f"🎉 Found Contract: {contract['tradingsymbol']} (Expiry: {contract['expiry']})")
    
    return {
        "tradingsymbol": contract['tradingsymbol'],
        "instrument_token": int(contract['instrument_token']),
        "strike": contract['strike']
    }
