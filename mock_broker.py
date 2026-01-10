# mock_broker.py
import datetime
import random
import threading
import time

# --- Global Data ---
MOCK_MARKET_DATA = {
    "NSE:NIFTY 50": 22000.0,
    "NSE:NIFTY BANK": 48000.0,
    "BSE:SENSEX": 72000.0,
    "NSE:RELIANCE": 2400.0,
    "NSE:INFY": 1600.0,
}

# Configuration
SIM_CONFIG = {
    "active": False,
    "volatility": 0.05,
    "speed": 1.0,
    "trend": "SIDEWAYS"
}

# --- Dynamic Expiry Logic (The Fix) ---
def get_next_weekly_expiry():
    """Calculates the date of the next Thursday (Standard Indian Expiry)"""
    today = datetime.date.today()
    # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
    # Calculate days to add to get to the next Thursday (3)
    days_ahead = (3 - today.weekday() + 7) % 7
    
    # If today is Thursday, we can use today as expiry, 
    # or add 7 days if you prefer next week. 
    # Here we default to 'Today' if it is Thursday, otherwise upcoming Thursday.
    next_thurs = today + datetime.timedelta(days=days_ahead)
    return next_thurs.strftime("%Y-%m-%d")

# This variable will now always be valid relative to when you run the script
CURRENT_EXPIRY = get_next_weekly_expiry()

# --- Background Market Simulator ---
def _market_heartbeat():
    print(f"💓 [MOCK MARKET] Simulation Heartbeat Started. Expiry set to: {CURRENT_EXPIRY}")
    while True:
        if SIM_CONFIG["active"]:
            trend = SIM_CONFIG["trend"]
            vol = SIM_CONFIG["volatility"]
            
            symbols = list(MOCK_MARKET_DATA.keys())
            for symbol in symbols:
                curr_price = MOCK_MARKET_DATA[symbol]
                
                # Trend Logic
                min_c, max_c = -vol, vol
                if trend == "BULLISH": min_c, max_c = -vol*0.2, vol*1.5
                elif trend == "BEARISH": min_c, max_c = -vol*1.5, vol*0.2
                
                # Option Logic
                is_pe = "PE" in symbol.upper()
                pct = random.uniform(min_c, max_c)
                if is_pe: pct = -pct
                
                # Apply
                movement = curr_price * (pct / 100.0)
                new_price = max(0.05, curr_price + movement)
                MOCK_MARKET_DATA[symbol] = round(new_price, 2)
                
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
        inst_list.append({"instrument_token": 1, "tradingsymbol": "NIFTY 50", "name": "NIFTY", "exchange": "NSE", "last_price": 0, "instrument_type": "EQ", "lot_size": 1, "expiry": ""})
        inst_list.append({"instrument_token": 2, "tradingsymbol": "NIFTY BANK", "name": "BANKNIFTY", "exchange": "NSE", "last_price": 0, "instrument_type": "EQ", "lot_size": 1, "expiry": ""})
        inst_list.append({"instrument_token": 3, "tradingsymbol": "RELIANCE", "name": "RELIANCE", "exchange": "NSE", "last_price": 0, "instrument_type": "EQ", "lot_size": 1, "expiry": ""})

        # Options (NIFTY) - 20 strikes around 22000
        # Uses CURRENT_EXPIRY calculated dynamically
        base = 22000
        for strike in range(base - 1000, base + 1000, 50):
            # Create a unique symbol string. 
            # Format: NIFTY + YY + M + DD + Strike + CE/PE (Rough approximation)
            # We simplify to: NIFTY + DateString + Type
            # E.g., NIFTY20241025CE22000
            
            # CE
            ce_sym = f"NIFTY{CURRENT_EXPIRY.replace('-','')}CE{strike}"
            inst_list.append({
                "instrument_token": strike, 
                "tradingsymbol": ce_sym, "name": "NIFTY", "exchange": "NFO",
                "last_price": 0, "instrument_type": "CE", "lot_size": 50,
                "expiry": CURRENT_EXPIRY, "strike": float(strike)
            })
            
            # PE
            pe_sym = f"NIFTY{CURRENT_EXPIRY.replace('-','')}PE{strike}"
            inst_list.append({
                "instrument_token": strike+10000, 
                "tradingsymbol": pe_sym, "name": "NIFTY", "exchange": "NFO",
                "last_price": 0, "instrument_type": "PE", "lot_size": 50,
                "expiry": CURRENT_EXPIRY, "strike": float(strike)
            })

            # Init Prices
            dist = (strike - base)
            ce_p = max(5.0, 100 - (dist*0.1)) if dist > 0 else max(5.0, 100 + (abs(dist)*0.1))
            pe_p = max(5.0, 100 - (abs(dist)*0.1)) if dist < 0 else max(5.0, 100 + (dist*0.1))

            if f"NFO:{ce_sym}" not in MOCK_MARKET_DATA: MOCK_MARKET_DATA[f"NFO:{ce_sym}"] = ce_p
            if f"NFO:{pe_sym}" not in MOCK_MARKET_DATA: MOCK_MARKET_DATA[f"NFO:{pe_sym}"] = pe_p

        return inst_list

    def login_url(self): return "/mock-login-trigger"
    def generate_session(self, r, s): return {"access_token": "mock", "user_id": "DEMO"}
    def set_access_token(self, a): pass
    def instruments(self, exchange=None): return self.mock_instruments
    def quote(self, i):
        res = {}
        for x in i:
            if x not in MOCK_MARKET_DATA: MOCK_MARKET_DATA[x] = 100.0
            p = MOCK_MARKET_DATA[x]
            res[x] = {"last_price": p, "ohlc": {"open": p, "high": p, "low": p, "close": p}}
        return res
    def ltp(self, i): return self.quote(i) # Reuse quote logic
    def place_order(self, **k): 
        print(f"✅ [MOCK] Order: {k.get('transaction_type')} {k.get('quantity')} {k.get('tradingsymbol')}")
        return "112233"
    def historical_data(self, *a, **k): return []
