import pandas as pd
from datetime import datetime

# Global cache
instrument_dump = None 

def fetch_instruments(kite):
    global instrument_dump
    if instrument_dump is not None:
        return

    print("📥 Downloading Instrument List...")
    try:
        instrument_dump = pd.DataFrame(kite.instruments("NFO"))
        # Ensure expiry is a string YYYY-MM-DD for JSON compatibility
        instrument_dump['expiry_str'] = pd.to_datetime(instrument_dump['expiry']).dt.strftime('%Y-%m-%d')
        instrument_dump['expiry_date'] = pd.to_datetime(instrument_dump['expiry']).dt.date
        print("✅ Instruments Downloaded.")
    except Exception as e:
        print(f"❌ Failed to fetch instruments: {e}")

def get_zerodha_symbol(common_name):
    """Normalizes names (e.g. 'NIFTY 50' -> 'NIFTY')"""
    common_name = common_name.upper()
    if "BANK" in common_name: return "BANKNIFTY"
    if "NIFTY" in common_name and "50" in common_name: return "NIFTY"
    if "NIFTY" in common_name: return "NIFTY"
    return common_name

def search_symbols(keyword):
    global instrument_dump
    if instrument_dump is None: return []
    keyword = keyword.upper()
    mask = (instrument_dump['segment'] == 'NFO-FUT') & (instrument_dump['name'].str.startswith(keyword))
    return instrument_dump[mask]['name'].unique().tolist()[:10]

def get_symbol_details(kite, symbol):
    """Returns Expiry List, Lot Size, and LTP"""
    global instrument_dump
    if instrument_dump is None: fetch_instruments(kite)
    
    symbol = get_zerodha_symbol(symbol)
    today = datetime.now().date()

    # 1. Get Expiries & Lot Size from Futures (most reliable)
    futs = instrument_dump[
        (instrument_dump['name'] == symbol) & 
        (instrument_dump['segment'] == 'NFO-FUT') &
        (instrument_dump['expiry_date'] >= today)
    ]
    
    if futs.empty:
        # Fallback to Options if no futures (rare for major indices)
        futs = instrument_dump[
            (instrument_dump['name'] == symbol) & 
            (instrument_dump['instrument_type'] == 'CE') &
            (instrument_dump['expiry_date'] >= today)
        ]

    if futs.empty: return None

    # Sort expiries
    expiries = sorted(futs['expiry_str'].unique().tolist())
    lot_size = int(futs.iloc[0]['lot_size'])

    # 2. Get LTP
    try:
        quote_sym = f"NSE:{symbol} 50" if symbol == "NIFTY" else f"NSE:{symbol}"
        if symbol == "BANKNIFTY": quote_sym = "NSE:NIFTY BANK"
        # For stocks, it's just NSE:SYMBOL
        if symbol not in ["NIFTY", "BANKNIFTY"]: quote_sym = f"NSE:{symbol}"
        
        ltp = kite.quote(quote_sym)[quote_sym]['last_price']
    except:
        ltp = 0

    return {
        "symbol": symbol,
        "ltp": ltp,
        "lot_size": lot_size,
        "expiries": expiries
    }

def get_chain_data(symbol, expiry_date, option_type, ltp):
    """Returns list of strikes with ITM/OTM labels for a specific expiry"""
    global instrument_dump
    
    # Filter for symbol, expiry, and type
    chain = instrument_dump[
        (instrument_dump['name'] == symbol) &
        (instrument_dump['expiry_str'] == expiry_date) &
        (instrument_dump['instrument_type'] == option_type)
    ]
    
    if chain.empty: return []

    strikes = sorted(chain['strike'].unique().tolist())
    
    # Calculate ATM (Closest strike to LTP)
    if not strikes: return []
    atm_strike = min(strikes, key=lambda x: abs(x - ltp))
    
    result = []
    for s in strikes:
        label = "OTM"
        if s == atm_strike:
            label = "ATM"
        elif option_type == "CE":
            label = "ITM" if ltp > s else "OTM"
        elif option_type == "PE":
            label = "ITM" if ltp < s else "OTM"
            
        result.append({"strike": s, "label": label})
        
    return result

def get_exact_symbol(symbol, expiry, strike, option_type):
    """Reconstructs the Tradingsymbol"""
    global instrument_dump
    
    # Logic for FUT
    if option_type == "FUT":
        mask = (
            (instrument_dump['name'] == symbol) &
            (instrument_dump['expiry_str'] == expiry) &
            (instrument_dump['instrument_type'] == "FUT")
        )
    else:
        # Logic for CE/PE
        mask = (
            (instrument_dump['name'] == symbol) &
            (instrument_dump['expiry_str'] == expiry) &
            (instrument_dump['strike'] == float(strike)) &
            (instrument_dump['instrument_type'] == option_type)
        )

    relevant = instrument_dump[mask]
    if relevant.empty: return None
    return relevant.iloc[0]['tradingsymbol']
