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

# Configuration for the simulation loop
SIM_CONFIG = {
    "active": False,       # Is the market moving?
    "volatility": 0.05,    # % movement per tick (0.05% is realistic volatility)
    "speed": 1.0           # Seconds between updates
}

# --- Background Market Simulator ---
def _market_heartbeat():
    """Runs in the background and moves prices randomly"""
    print("💓 [MOCK MARKET] Simulation Heartbeat Started")
    while True:
        if SIM_CONFIG["active"]:
            for symbol in list(MOCK_MARKET_DATA.keys()):
                curr_price = MOCK_MARKET_DATA[symbol]
                
                # Calculate random move: -Volatility to +Volatility
                change_pct = random.uniform(-SIM_CONFIG["volatility"], SIM_CONFIG["volatility"])
                movement = curr_price * (change_pct / 100.0)
                
                # Apply move and round to 2 decimals
                new_price = round(curr_price + movement, 2)
                MOCK_MARKET_DATA[symbol] = new_price
                
        time.sleep(SIM_CONFIG["speed"])

# Start the thread immediately when imported
t = threading.Thread(target=_market_heartbeat, daemon=True)
t.start()

# --- Mock Kite Class (Same as before, slight cleanup) ---
class MockKiteConnect:
    def __init__(self, api_key=None, **kwargs):
        print("⚠️ [MOCK BROKER] Initialized.")

    def login_url(self): return "/mock-login-trigger"

    def generate_session(self, request_token, api_secret):
        return {"access_token": "mock_token", "user_id": "DEMO"}

    def set_access_token(self, access_token): pass

    def instruments(self, exchange=None):
        # minimal dummy list for search to work
        return [
            {"instrument_token": 1, "tradingsymbol": "NIFTY 50", "name": "NIFTY", "exchange": "NSE", "last_price": 0, "instrument_type": "EQ", "lot_size": 1, "expiry": ""},
            {"instrument_token": 2, "tradingsymbol": "RELIANCE", "name": "RELIANCE", "exchange": "NSE", "last_price": 0, "instrument_type": "EQ", "lot_size": 1, "expiry": ""},
        ]

    def quote(self, instruments):
        # Return the CURRENT dynamic price from MOCK_MARKET_DATA
        res = {}
        for inst in instruments:
            price = MOCK_MARKET_DATA.get(inst, 100.0)
            res[inst] = {"last_price": price, "ohlc": {"open": price, "high": price, "low": price, "close": price}}
        return res
    
    def ltp(self, instruments):
        return {i: {"last_price": MOCK_MARKET_DATA.get(i, 100.0)} for i in instruments}

    def place_order(self, **kwargs):
        print(f"✅ [MOCK] Order Placed: {kwargs.get('transaction_type')} {kwargs.get('quantity')} {kwargs.get('tradingsymbol')}")
        return "112233"

    def historical_data(self, *args, **kwargs):
        return [] # Empty for now
