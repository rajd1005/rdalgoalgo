# mock_broker.py
import datetime
import random
import threading
import time
import re

# --- Global Data ---
MOCK_MARKET_DATA = {
    "NSE:NIFTY 50": 22000.0,
    "NSE:NIFTY BANK": 48000.0,
    "BSE:SENSEX": 72000.0,
    "NSE:RELIANCE": 2400.0,
}

# Configuration
SIM_CONFIG = {
    "active": False,
    "volatility": 0.05,
    "speed": 1.0,
    "trend": "SIDEWAYS"
}

# Helper: Get Next Thursday
def get_next_weekly_expiry():
    today = datetime.date.today()
    days_ahead = (3 - today.weekday() + 7) % 7
    return (today + datetime.timedelta(days=days_ahead)).strftime("%Y-%m-%d")

CURRENT_EXPIRY = get_next_weekly_expiry()

# --- OPTION PRICING ENGINE ---
def calculate_option_price(spot_price, strike_price, option_type):
    """
    Calculates a realistic Option Price = Intrinsic Value + Time Value
    """
    # 1. Intrinsic Value (Real Value)
    intrinsic = 0.0
    if option_type == "CE":
        intrinsic = max(0.0, spot_price - strike_price)
    else: # PE
        intrinsic = max(0.0, strike_price - spot_price)
    
    # 2. Time Value (Extrinsic Value)
    # Highest at ATM, decreases as we go further ITM/OTM
    distance = abs(spot_price - strike_price)
    
    # Simple curve: Max Time Value ~150, decays with distance
    # Width of decay ~400 points
    time_value = 150 * (0.995 ** distance) 
    
    # Add some randomness (IV Fluctuation)
    noise = random.uniform(-2, 2)
    
    price = intrinsic + time_value + noise
    return round(max(0.05, price), 2)

# --- Background Market Simulator ---
def _market_heartbeat():
    print(f"💓 [MOCK MARKET] Simulation Heartbeat Started. Expiry: {CURRENT_EXPIRY}")
    while True:
        if SIM_CONFIG["active"]:
            trend = SIM_CONFIG["trend"]
            vol = SIM_CONFIG["volatility"]
            
            # 1. Update INDICES first (The Drivers)
            indices = ["NSE:NIFTY 50", "NSE:NIFTY BANK", "BSE:SENSEX", "NSE:RELIANCE"]
            for sym in indices:
                curr = MOCK_MARKET_DATA.get(sym, 10000)
                
                # Trend Logic
                bias = 0
                if trend == "BULLISH": bias = vol * 0.5
                elif trend == "BEARISH": bias = -vol * 0.5
                
                change = random.uniform(-vol, vol) + bias
                new_price = curr * (1 + change/100.0)
                MOCK_MARKET_DATA[sym] = round(new_price, 2)

            # 2. Update OPTIONS based on new Index Price
            keys = list(MOCK_MARKET_DATA.keys())
            for sym in keys:
                if ":NIFTY" in sym and ("CE" in sym or "PE" in sym):
                    # Extract Strike and Type
                    # Format approximation: NIFTY...CE22000
                    try:
                        is_ce = "CE" in sym
                        type_ = "CE" if is_ce else "PE"
                        
                        # Parse strike from end of string
                        match = re.search(r'(CE|PE)(\d+(\.\d+)?)', sym)
                        if match:
                            strike = float(match.group(2))
                            spot = MOCK_MARKET_DATA["NSE:NIFTY 50"] # Hardcoded link to NIFTY
                            
                            new_opt_price = calculate_option_price(spot, strike, type_)
                            MOCK_MARKET_DATA[sym] = new_opt_price
                    except:
                        pass # specific parsing error

        time.sleep(SIM_CONFIG["speed"])

t = threading.Thread(target=_market_heartbeat, daemon=True)
t.start()

# --- Mock Kite Class ---
class MockKiteConnect:
    def __init__(self, api_key=None, **kwargs):
        print("⚠️ [MOCK BROKER] Initialized.")
        self.mock_instruments = self._generate_instruments()

    def _generate_instruments(self):
        inst_list = []
        # Indices
        inst_list.append({"instrument_token": 256265, "tradingsymbol": "NIFTY 50", "name": "NIFTY", "exchange": "NSE", "last_price": 0, "instrument_type": "EQ", "lot_size": 1, "expiry": ""})
        inst_list.append({"instrument_token": 260105, "tradingsymbol": "NIFTY BANK", "name": "BANKNIFTY", "exchange": "NSE", "last_price": 0, "instrument_type": "EQ", "lot_size": 1, "expiry": ""})
        inst_list.append({"instrument_token": 738561, "tradingsymbol": "RELIANCE", "name": "RELIANCE", "exchange": "NSE", "last_price": 0, "instrument_type": "EQ", "lot_size": 1, "expiry": ""})

        # Options Generation (Center around 22000 initially)
        base = 22000
        for strike in range(base - 1000, base + 1000, 50):
            # CE
            ce_sym = f"NIFTY{CURRENT_EXPIRY.replace('-','')}CE{strike}"
            inst_list.append({"instrument_token": strike, "tradingsymbol": ce_sym, "name": "NIFTY", "exchange": "NFO", "last_price": 0, "instrument_type": "CE", "lot_size": 50, "expiry": CURRENT_EXPIRY, "strike": float(strike)})
            
            # PE
            pe_sym = f"NIFTY{CURRENT_EXPIRY.replace('-','')}PE{strike}"
            inst_list.append({"instrument_token": strike+10000, "tradingsymbol": pe_sym, "name": "NIFTY", "exchange": "NFO", "last_price": 0, "instrument_type": "PE", "lot_size": 50, "expiry": CURRENT_EXPIRY, "strike": float(strike)})

            # Init Prices
            spot = MOCK_MARKET_DATA["NSE:NIFTY 50"]
            if f"NFO:{ce_sym}" not in MOCK_MARKET_DATA: 
                MOCK_MARKET_DATA[f"NFO:{ce_sym}"] = calculate_option_price(spot, strike, "CE")
            if f"NFO:{pe_sym}" not in MOCK_MARKET_DATA: 
                MOCK_MARKET_DATA[f"NFO:{pe_sym}"] = calculate_option_price(spot, strike, "PE")

        return inst_list

    # Standard Mock Methods
    def login_url(self): return "/mock-login-trigger"
    def generate_session(self, r, s): return {"access_token": "mock", "user_id": "DEMO"}
    def set_access_token(self, a): pass
    def instruments(self, exchange=None): return self.mock_instruments
    def quote(self, i):
        res = {}
        for x in i:
            # Auto Discovery
            if x not in MOCK_MARKET_DATA: MOCK_MARKET_DATA[x] = 100.0
            p = MOCK_MARKET_DATA[x]
            res[x] = {"last_price": p, "ohlc": {"open": p, "high": p, "low": p, "close": p}}
        return res
    def ltp(self, i): return self.quote(i)
    def place_order(self, **k): 
        print(f"✅ [MOCK] Order: {k.get('transaction_type')} {k.get('quantity')} {k.get('tradingsymbol')}")
        return f"ORD_{random.randint(10000,99999)}"
    def historical_data(self, *a, **k): return []
