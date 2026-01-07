import pandas as pd
from datetime import datetime

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
    Robust mapping for Indices.
    """
    upper_name = common_name.upper()
    
    # 1. Handle BANKNIFTY variations
    if "BANK" in upper_name:
        return "BANKNIFTY"
    
    # 2. Handle NIFTY variations
    if "NIFTY" in upper_name:
        if "FIN" in upper_name: return "FINNIFTY"
        return "NIFTY" # Defaults to Nifty 50
        
    return upper_name

def search_symbols(keyword):
    global instrument_dump
    if instrument_dump is None: return []
    keyword = keyword.upper()
    
    # Search in Futures (NFO) OR Stocks (NSE)
    mask = (
        ((instrument_dump['segment'] == 'NFO-FUT') | (instrument_dump['segment'] == 'NSE')) & 
        (instrument_dump['name'].str.contains(keyword, na=False)) # 'contains' is better than 'startswith' for "Nifty Bank"
    )
    return instrument_dump[mask]['name'].unique().tolist()[:10]

def get_symbol_details(kite, symbol):
    global instrument_dump
    if instrument_dump is None: fetch_instruments(kite)
    
    # Normalize Name (e.g. "Nifty Bank" -> "BANKNIFTY")
    clean_symbol = get_zerodha_symbol(symbol)
    today = datetime.now().date()

    # 1. Get Underlying LTP (Spot Price)
    ltp = 0
    try:
        quote_sym = ""
        if clean_symbol == "NIFTY": quote_sym = "NSE:NIFTY 50"
        elif clean_symbol == "BANKNIFTY": quote_sym = "NSE:NIFTY BANK"
        elif clean_symbol == "FINNIFTY": quote_sym = "NSE:NIFTY FIN SERVICE"
        else: quote_sym = f"NSE:{clean_symbol}" # Stocks
        
        ltp = kite.quote(quote_sym)[quote_sym]['last_price']
    except:
        ltp = 0 # Fallback

    # 2. Get Lot Size & Expiries from FUTURES
    lot_size = 1 # Default for Equity
    fut_exps = []
    
    # Filter for the cleaned symbol in Futures
    futs = instrument_dump[
        (instrument_dump['name'] == clean_symbol) & 
        (instrument_dump['segment'] == 'NFO-FUT')
    ]
    
    if not futs.empty:
        lot_size = int(futs.iloc[0]['lot_size'])
        fut_exps = sorted(futs[futs['expiry_date'] >= today]['expiry_str'].unique().tolist())
    
    # 3. Get Option Expiries
    opts = instrument_dump[
        (instrument_dump['name'] == clean_symbol) & 
        (instrument_dump['instrument_type'] == 'CE')
    ]
    opt_exps = sorted(opts[opts['expiry_date'] >= today]['expiry_str'].unique().tolist())

    return {
        "symbol": clean_symbol, # Send back the cleaned name
        "ltp": ltp,
        "lot_size": lot_size,
        "fut_expiries": fut_exps,
        "opt_expiries": opt_exps
    }

# ... (Keep get_chain_data, get_specific_ltp, get_exact_symbol as they were) ...
# Copy them from previous response if needed, no changes required there.
def get_chain_data(symbol, expiry_date, option_type, ltp):
    """Returns strikes with labels"""
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
    tradingsymbol = ""
    exchange = "NFO"
    if inst_type == "EQ":
        tradingsymbol = symbol
        exchange = "NSE"
    elif inst_type == "FUT":
        mask = (instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['instrument_type'] == "FUT")
        if not mask.any(): return 0
        tradingsymbol = instrument_dump[mask].iloc[0]['tradingsymbol']
    else:
        mask = (instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['strike'] == float(strike)) & (instrument_dump['instrument_type'] == inst_type)
        if not mask.any(): return 0
        tradingsymbol = instrument_dump[mask].iloc[0]['tradingsymbol']

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
        mask = (instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['strike'] == float(strike)) & (instrument_dump['instrument_type'] == option_type)
    if not mask.any(): return None
    return instrument_dump[mask].iloc[0]['tradingsymbol']
