# mock_broker.py
import datetime
import random
import threading
import time

# --- Global Data ---
# Stores current prices for everything
MOCK_MARKET_DATA = {
    "NSE:NIFTY 50": 22000.0,
    "NSE:NIFTY BANK": 48000.0,
    "BSE:SENSEX": 72000.0,
    "NSE:RELIANCE": 2400.0,
    "NSE:INFY": 1600.0,
}

# Configuration for the simulation loop
SIM_CONFIG = {
    "active": False,       # On/Off
    "volatility": 0.05,    # % movement per tick
    "speed": 1.0,          # Seconds between updates
    "trend": "SIDEWAYS"    # SIDEWAYS, BULLISH, BEARISH
}

# --- Background Market Simulator ---
def _market_heartbeat():
    """Runs in the background and moves prices based on Trend & Volatility"""
    print("💓 [MOCK MARKET] Simulation Heartbeat Started")
    while True:
        if SIM_CONFIG["active"]:
            trend = SIM_CONFIG["trend"]
            vol = SIM_CONFIG["volatility"]
            
            # Create a snapshot of keys to avoid runtime errors if keys are added during iteration
            symbols = list(MOCK_MARKET_DATA.keys())
            
            for symbol in symbols:
                curr_price = MOCK_MARKET_DATA[symbol]
                
                # 1. Determine Direction Bias based on Trend Setting
                # Default: Random Walk (Sideways)
                min_change = -vol
                max_change = vol
                
                if trend == "BULLISH":
                    min_change = -vol * 0.2  # Small downside
                    max_change = vol * 1.5   # Big upside
                elif trend == "BEARISH":
                    min_change = -vol * 1.5  # Big downside
                    max_change = vol * 0.2   # Small upside
                
                # 2. Smart Options Logic (Invert logic for PE)
                is_pe = "PE" in symbol.upper()
                
                # Generate percentage move
                move_pct = random.uniform(min_change, max_change)
                
                # If it's a PE option, INVERT the move (Index UP = PE DOWN)
                if is_pe:
                    move_pct = -move_pct
                
                # 3. Apply Price Change
                movement = curr_price * (move_pct / 100.0)
                new_price = curr_price + movement
                
                # Prevent negative prices
                if new_price < 0.05: new_price = 0.05
                
                MOCK_MARKET_DATA[symbol] = round(new_price, 2)
                
        time.sleep(SIM_CONFIG["speed"])

# Start the thread
t = threading.Thread(target=_market_heartbeat, daemon=True)
t.start()

# --- Mock Kite Class ---
class MockKiteConnect:
    def __init__(self, api_key=None, **kwargs):
        print("⚠️ [MOCK BROKER] Initialized.")

    def login_url(self): return "/mock-login-trigger"

    def generate_session(self, request_token, api_secret):
        return {"access_token": "mock_token", "user_id": "DEMO"}

    def set_access_token(self, access_token): pass

    def instruments(self, exchange=None):
        # Minimal dummy list
        return [
            {"instrument_token": 1, "tradingsymbol": "NIFTY 50", "name": "NIFTY", "exchange": "NSE", "last_price": 0, "instrument_type": "EQ", "lot_size": 1, "expiry": ""},
            {"instrument_token": 2, "tradingsymbol": "RELIANCE", "name": "RELIANCE", "exchange": "NSE", "last_price": 0, "instrument_type": "EQ", "lot_size": 1, "expiry": ""},
        ]

    def quote(self, instruments):
        res = {}
        for inst in instruments:
            # AUTO-DISCOVERY: If app asks for a symbol we don't have, add it!
            # This ensures new Options added in UI start moving immediately.
            if inst not in MOCK_MARKET_DATA:
                # Give it a default price if missing
                MOCK_MARKET_DATA[inst] = 100.0
                
            price = MOCK_MARKET_DATA[inst]
            res[inst] = {"last_price": price, "ohlc": {"open": price, "high": price, "low": price, "close": price}}
        return res
    
    def ltp(self, instruments):
        # Same auto-discovery logic for LTP calls
        res = {}
        for inst in instruments:
            if inst not in MOCK_MARKET_DATA:
                MOCK_MARKET_DATA[inst] = 100.0
            res[inst] = {"last_price": MOCK_MARKET_DATA[inst]}
        return res

    def place_order(self, **kwargs):
        print(f"✅ [MOCK] Order Placed: {kwargs.get('transaction_type')} {kwargs.get('quantity')} {kwargs.get('tradingsymbol')}")
        return "112233"

    def historical_data(self, *args, **kwargs):
        return []
