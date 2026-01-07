import pandas as pd
from datetime import datetime

# Global cache
instrument_dump = None 

def fetch_instruments(kite):
    global instrument_dump
    if instrument_dump is not None: return

    print("📥 Downloading Instrument List...")
    try:
        instrument_dump = pd.DataFrame(kite.instruments()) # Download ALL (NSE+NFO)
        # Create helper columns
        instrument_dump['expiry_str'] = pd.to_datetime(instrument_dump['expiry']).dt.strftime('%Y-%m-%d')
        instrument_dump['expiry_date'] = pd.to_datetime(instrument_dump['expiry']).dt.date
        print("✅ Instruments Downloaded.")
    except Exception as e:
        print(f"❌ Failed to fetch instruments: {e}")

def get_zerodha_symbol(common_name):
    common_name = common_name.upper()
    if "BANK" in common_name: return "BANKNIFTY"
    if "NIFTY" in common_name and "50" in common_name: return "NIFTY"
    if "NIFTY" in common_name: return "NIFTY"
    return common_name

def search_symbols(keyword):
    """Searches Futures (NFO) and Stocks (NSE)"""
    global instrument_dump
    if instrument_dump is None: return []
    keyword = keyword.upper()
    
    # Search in Futures OR Equities
    mask = (
        ((instrument_dump['segment'] == 'NFO-FUT') | (instrument_dump['segment'] == 'NSE')) & 
        (instrument_dump['name'].str.startswith(keyword))
    )
    return instrument_dump[mask]['name'].unique().tolist()[:10]

def get_symbol_details(kite, symbol):
    """Returns separate Expiry lists for FUT and OPT"""
    global instrument_dump
    if instrument_dump is None: fetch_instruments(kite)
    
    symbol = get_zerodha_symbol(symbol)
    today = datetime.now().date()

    # 1. Get Underlying LTP
    ltp = 0
    try:
        quote_sym = f"NSE:{symbol} 50" if symbol == "NIFTY" else f"NSE:{symbol}"
        if symbol == "BANKNIFTY": quote_sym = "NSE:NIFTY BANK"
        # Check if it's a stock in NSE
        if not instrument_dump[(instrument_dump['name'] == symbol) & (instrument_dump['segment'] == 'NSE')].empty:
             quote_sym = f"NSE:{symbol}"
             
        ltp = kite.quote(quote_sym)[quote_sym]['last_price']
    except:
        ltp = 0

    # 2. Get Lot Size (From Futures preferred)
    lot_size = 1
    futs = instrument_dump[(instrument_dump['name'] == symbol) & (instrument_dump['segment'] == 'NFO-FUT')]
    if not futs.empty:
        lot_size = int(futs.iloc[0]['lot_size'])

    # 3. Get Expiries
    # Future Expiries
    fut_exps = sorted(futs[futs['expiry_date'] >= today]['expiry_str'].unique().tolist())
    
    # Option Expiries
    opts = instrument_dump[(instrument_dump['name'] == symbol) & (instrument_dump['instrument_type'] == 'CE')]
    opt_exps = sorted(opts[opts['expiry_date'] >= today]['expiry_str'].unique().tolist())

    return {
        "symbol": symbol,
        "ltp": ltp,
        "lot_size": lot_size,
        "fut_expiries": fut_exps,
        "opt_expiries": opt_exps
    }

def get_chain_data(symbol, expiry_date, option_type, ltp):
    """Returns strikes with labels"""
    global instrument_dump
    
    chain = instrument_dump[
        (instrument_dump['name'] == symbol) &
        (instrument_dump['expiry_str'] == expiry_date) &
        (instrument_dump['instrument_type'] == option_type)
    ]
    
    if chain.empty: return []

    strikes = sorted(chain['strike'].unique().tolist())
    if not strikes: return []
    
    atm_strike = min(strikes, key=lambda x: abs(x - ltp))
    
    result = []
    for s in strikes:
        label = ""
        if s == atm_strike:
            label = "🔴 ATM" # RED SIGN
        elif option_type == "CE":
            label = "ITM" if ltp > s else "OTM"
        elif option_type == "PE":
            label = "ITM" if ltp < s else "OTM"
            
        result.append({"strike": s, "label": label})
        
    return result

def get_specific_ltp(kite, symbol, expiry, strike, inst_type):
    """Finds the exact instrument and fetches its LTP"""
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
    
    if option_type == "EQ":
        return symbol # Return pure symbol for Equity
        
    if option_type == "FUT":
        mask = (instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['instrument_type'] == "FUT")
    else:
        mask = (instrument_dump['name'] == symbol) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['strike'] == float(strike)) & (instrument_dump['instrument_type'] == option_type)

    if not mask.any(): return None
    return instrument_dump[mask].iloc[0]['tradingsymbol']
