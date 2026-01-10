# mock_broker.py
import datetime
import random
import threading
import time

# --- Global Data ---
# Stores current prices. We initialize with Indices.
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

# --- Helper: Generate Valid Expiry Date ---
def get_next_expiry():
    # Returns a string 'YYYY-MM-DD' for a date 30 days from now
    # This ensures the option chain is always "valid" and not expired
    fut = datetime.date.today() + datetime.timedelta(days=30)
    return fut.strftime("%Y-%m-%d")

CURRENT_EXPIRY = get_next_expiry()

# --- Background Market Simulator ---
def _market_heartbeat():
    """Runs in the background and moves prices based on Trend & Volatility"""
    print("💓 [MOCK MARKET] Simulation Heartbeat Started")
    while True:
        if SIM_CONFIG["active"]:
            trend = SIM_CONFIG["trend"]
            vol = SIM_CONFIG["volatility"]
            
            # Snapshot keys to avoid runtime modification errors
            symbols = list(MOCK_MARKET_DATA.keys())
            
            for symbol in symbols:
                curr_price = MOCK_MARKET_DATA[symbol]
                
                # 1. Determine Direction Bias
                min_change, max_change = -vol, vol
                
                if trend == "BULLISH":
                    min_change, max_change = -vol * 0.2, vol * 1.5
                elif trend == "BEARISH":
                    min_change, max_change = -vol * 1.5, vol * 0.2
                
                # 2. Smart Options Logic (Invert logic for PE)
                is_pe = "PE" in symbol.upper()
                
                # Generate percentage move
                move_pct = random.uniform(min_change, max_change)
                if is_pe: move_pct = -move_pct # Index UP = PE DOWN
                
                # 3. Apply Price Change
                movement = curr_price * (move_pct / 100.0)
                new_price = max(0.05, curr_price + movement)
                
                MOCK_MARKET_DATA[symbol] = round(new_price, 2)
                
        time.sleep(SIM_CONFIG["speed"])

# Start the thread
t = threading.Thread(target=_market_heartbeat, daemon=True)
t.start()

# --- Mock Kite Class ---
class MockKiteConnect:
    def __init__(self, api_key=None, **kwargs):
        print("⚠️ [MOCK BROKER] Initialized.")
        self.mock_instruments = self._generate_instruments()

    def _generate_instruments(self):
        """Generates a realistic Instrument Dump for smart_trader.py"""
        inst_list = []
        
        # 1. Add Indices
        inst_list.append({"instrument_token": 1, "tradingsymbol": "NIFTY 50", "name": "NIFTY", "exchange": "NSE", "last_price": 0, "instrument_type": "EQ", "lot_size": 1, "expiry": ""})
        inst_list.append({"instrument_token": 2, "tradingsymbol": "NIFTY BANK", "name": "BANKNIFTY", "exchange": "NSE", "last_price": 0, "instrument_type": "EQ", "lot_size": 1, "expiry": ""})
        inst_list.append({"instrument_token": 3, "tradingsymbol": "RELIANCE", "name": "RELIANCE", "exchange": "NSE", "last_price": 0, "instrument_type": "EQ", "lot_size": 1, "expiry": ""})

        # 2. Generate Options for NIFTY (Strike 21000 to 23000)
        # This matches the MOCK_MARKET_DATA['NSE:NIFTY 50'] price of 22000
        base_price = 22000
        for strike in range(base_price - 1000, base_price + 1000, 50):
            # CE
            ce_sym = f"NIFTY{CURRENT_EXPIRY.replace('-','')}CE{strike}"
            inst_list.append({
                "instrument_token": strike, # Dummy token
                "tradingsymbol": ce_sym,
                "name": "NIFTY",
                "exchange": "NFO",
                "last_price": 0,
                "instrument_type": "CE",
                "lot_size": 50,
                "expiry": CURRENT_EXPIRY,
                "strike": float(strike)
            })
            # PE
            pe_sym = f"NIFTY{CURRENT_EXPIRY.replace('-','')}PE{strike}"
            inst_list.append({
                "instrument_token": strike+10000,
                "tradingsymbol": pe_sym,
                "name": "NIFTY",
                "exchange": "NFO",
                "last_price": 0,
                "instrument_type": "PE",
                "lot_size": 50,
                "expiry": CURRENT_EXPIRY,
                "strike": float(strike)
            })
            
            # Initialize Price in Market Data if missing
            # Simple Logic: ATM ~ 100, OTM gets cheaper
            dist = (strike - base_price)
            ce_price = max(5.0, 100 - (dist * 0.1)) if dist > 0 else max(5.0, 100 + (abs(dist) * 0.1))
            pe_price = max(5.0, 100 - (abs(dist) * 0.1)) if dist < 0 else max(5.0, 100 + (dist * 0.1))

            if f"NFO:{ce_sym}" not in MOCK_MARKET_DATA: MOCK_MARKET_DATA[f"NFO:{ce_sym}"] = ce_price
            if f"NFO:{pe_sym}" not in MOCK_MARKET_DATA: MOCK_MARKET_DATA[f"NFO:{pe_sym}"] = pe_price

        return inst_list

    def login_url(self): return "/mock-login-trigger"

    def generate_session(self, request_token, api_secret):
        return {"access_token": "mock_token", "user_id": "DEMO"}

    def set_access_token(self, access_token): pass

    def instruments(self, exchange=None):
        return self.mock_instruments

    def quote(self, instruments):
        res = {}
        for inst in instruments:
            # Auto-Discovery for unknown symbols
            if inst not in MOCK_MARKET_DATA:
                MOCK_MARKET_DATA[inst] = 100.0
                
            price = MOCK_MARKET_DATA[inst]
            res[inst] = {"last_price": price, "ohlc": {"open": price, "high": price, "low": price, "close": price}}
        return res
    
    def ltp(self, instruments):
        res = {}
        for inst in instruments:
            if inst not in MOCK_MARKET_DATA: MOCK_MARKET_DATA[inst] = 100.0
            res[inst] = {"last_price": MOCK_MARKET_DATA[inst]}
        return res

    def place_order(self, **kwargs):
        print(f"✅ [MOCK] Order Placed: {kwargs.get('transaction_type')} {kwargs.get('quantity')} {kwargs.get('tradingsymbol')}")
        return "112233"

    def historical_data(self, *args, **kwargs):
        return []
