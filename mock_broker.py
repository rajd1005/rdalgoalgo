# mock_broker.py
import datetime
import random

# Global store for simulated market prices
# Format: {"NSE:RELIANCE": 2500.0, "NSE:NIFTY 50": 22000.0}
MOCK_MARKET_DATA = {
    "NSE:NIFTY 50": 22000.0,
    "NSE:NIFTY BANK": 48000.0,
    "BSE:SENSEX": 72000.0,
    "NSE:RELIANCE": 2400.0,
    "NSE:INFY": 1600.0,
    "NSE:TATASTEEL": 150.0
}

# Generate some dummy instruments for the search and chain to work
DUMMY_INSTRUMENTS = []
def _add_inst(exch, symbol, token, lot, name, type_="EQ", strike=0, expiry=""):
    DUMMY_INSTRUMENTS.append({
        "instrument_token": token, "exchange_token": token, "tradingsymbol": symbol,
        "name": name, "last_price": 0, "expiry": expiry, "strike": strike,
        "tick_size": 0.05, "lot_size": lot, "instrument_type": type_,
        "segment": exch, "exchange": exch
    })

# Add Indices and Equities
_add_inst("NSE", "NIFTY 50", 256265, 1, "NIFTY")
_add_inst("NSE", "NIFTY BANK", 260105, 1, "BANKNIFTY")
_add_inst("BSE", "SENSEX", 569852, 1, "SENSEX")
_add_inst("NSE", "RELIANCE", 738561, 1, "RELIANCE")

# Add some Options for NIFTY (Current Month) - Adjust expiry as needed for your testing
curr_expiry = (datetime.date.today().replace(day=28)).strftime("%Y-%m-%d") # Mock expiry
base_strike = 22000
for i in range(-5, 6):
    strike = base_strike + (i * 50)
    _add_inst("NFO", f"NIFTY24{curr_expiry.replace('-','')}CE{strike}", 10000+i, 50, "NIFTY", "CE", strike, curr_expiry)
    _add_inst("NFO", f"NIFTY24{curr_expiry.replace('-','')}PE{strike}", 20000+i, 50, "NIFTY", "PE", strike, curr_expiry)
    MOCK_MARKET_DATA[f"NFO:NIFTY24{curr_expiry.replace('-','')}CE{strike}"] = 100.0 + (i*10)
    MOCK_MARKET_DATA[f"NFO:NIFTY24{curr_expiry.replace('-','')}PE{strike}"] = 100.0 - (i*10)


class MockKiteConnect:
    def __init__(self, api_key=None, **kwargs):
        self.api_key = api_key
        self.access_token = None
        print("⚠️ [MOCK BROKER] Initialized. No real trades will be placed.")

    def login_url(self):
        return "/mock-login-trigger" # Just a dummy link

    def generate_session(self, request_token, api_secret):
        print(f"⚠️ [MOCK BROKER] Session Generated for token: {request_token}")
        return {"access_token": "mock_access_token_123", "public_token": "mock_pub", "user_id": "DEMO_USER"}

    def set_access_token(self, access_token):
        self.access_token = access_token
        print(f"⚠️ [MOCK BROKER] Access Token Set: {access_token}")

    def instruments(self, exchange=None):
        # Return dummy list for smart_trader.py
        return DUMMY_INSTRUMENTS

    def quote(self, instruments):
        # instruments is a list like ['NSE:NIFTY 50', 'NFO:NIFTY24...']
        response = {}
        for inst in instruments:
            price = MOCK_MARKET_DATA.get(inst, 0)
            # If price is 0, maybe generate a random one to prevent UI errors
            if price == 0: price = 100.0 
            
            response[inst] = {
                "instrument_token": 12345,
                "timestamp": datetime.datetime.now(),
                "last_price": price,
                "ohlc": {"open": price, "high": price+5, "low": price-5, "close": price},
                "depth": {"buy": [], "sell": []}
            }
        return response

    def ltp(self, instruments):
        # Similar to quote but only prices
        return {i: {"instrument_token": 123, "last_price": MOCK_MARKET_DATA.get(i, 0)} for i in instruments}

    def place_order(self, tradingsymbol, exchange, transaction_type, quantity, order_type, product, price=None, trigger_price=None, **kwargs):
        order_id = f"MOCK_ORD_{random.randint(1000, 9999)}"
        print(f"✅ [MOCK BROKER] Order Placed: {transaction_type} {quantity} {tradingsymbol} @ {exchange}. ID: {order_id}")
        return order_id

    def historical_data(self, instrument_token, from_date, to_date, interval, continuous=False, oi=False):
        # Return fake candles for the Simulator chart/history check
        # Simple flat line or mild volatility based on current mock price
        base_price = 100.0 # Default
        # Try to find symbol for token
        for k, v in MOCK_MARKET_DATA.items():
            # In a real mock we would map tokens map properly, here we guess
            pass
            
        candles = []
        curr = from_date
        while curr <= to_date:
            o = base_price + random.uniform(-2, 2)
            h = o + 2
            l = o - 2
            c = o + random.uniform(-1, 1)
            candles.append({"date": curr, "open": o, "high": h, "low": l, "close": c, "volume": 1000})
            curr += datetime.timedelta(minutes=1)
        return candles
