import json
import os
import time
import smart_trader  # Your existing module
from datetime import datetime

# --- FILE PERSISTENCE ---
TRADES_FILE = 'active_trades.json'

def load_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, 'r') as f:
            return json.load(f)
    return []

def save_trades(trades):
    with open(TRADES_FILE, 'w') as f:
        json.dump(trades, f, default=str, indent=4)

# --- CORE LOGIC ---

def create_trade(kite, mode, index, option_type, quantity, sl_points):
    """
    1. Finds the ATM symbol.
    2. Calculates 5 Targets based on Risk.
    3. Places order (Real or Simulated).
    """
    trades = load_trades()
    
    # A. Smart Option Search
    # Note: We use a dummy LTP if market is closed, else fetch live
    try:
        quote = kite.quote(f"NSE:{index}")
        ltp = quote[f"NSE:{index}"]["last_price"]
    except:
        ltp = 24000 # Fallback for testing
        
    contract = smart_trader.find_option_symbol(kite, underlying=index, option_type=option_type, ltp=ltp)
    
    if not contract:
        return {"status": "error", "message": "No contract found"}

    symbol = contract['tradingsymbol']
    
    # B. Execution Logic
    entry_price = 0
    order_id = "SIMULATED"
    
    if mode == "LIVE":
        try:
            # LIVE ORDER PLACEMENT
            order_id = kite.place_order(
                tradingsymbol=symbol,
                exchange=kite.EXCHANGE_NFO,
                transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=quantity,
                order_type=kite.ORDER_TYPE_MARKET,
                product=kite.PRODUCT_MIS,
                variety=kite.VARIETY_REGULAR
            )
            # Fetch execution price (simplified)
            entry_price = 100.0 # You would fetch this from kite.orders()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    else:
        # PAPER ENTRY
        entry_price = 100.0 # Simulated Price

    # C. Risk Calculation (5 Targets)
    risk = sl_points
    targets = [
        entry_price + (risk * 0.5), # T1
        entry_price + (risk * 1.0), # T2
        entry_price + (risk * 1.5), # T3
        entry_price + (risk * 2.0), # T4
        entry_price + (risk * 3.0)  # T5
    ]
    
    trade_record = {
        "id": int(time.time()),
        "symbol": symbol,
        "mode": mode,
        "status": "OPEN",
        "entry_price": entry_price,
        "quantity": quantity,
        "sl": entry_price - risk,
        "targets": targets,
        "t1_hit": False,
        "current_ltp": entry_price
    }
    
    trades.append(trade_record)
    save_trades(trades)
    return {"status": "success", "trade": trade_record}

def promote_to_live(kite, trade_id):
    """Workflow: Paper -> Live"""
    trades = load_trades()
    for trade in trades:
        if trade['id'] == int(trade_id) and trade['mode'] == "PAPER":
            try:
                # EXECUTE REAL ORDER
                kite.place_order(
                    tradingsymbol=trade['symbol'],
                    exchange=kite.EXCHANGE_NFO,
                    transaction_type=kite.TRANSACTION_TYPE_BUY,
                    quantity=trade['quantity'],
                    order_type=kite.ORDER_TYPE_MARKET,
                    product=kite.PRODUCT_MIS
                )
                trade['mode'] = "LIVE"
                trade['status'] = "PROMOTED_LIVE" # Or keep OPEN
                save_trades(trades)
                return True
            except Exception as e:
                print(f"Promotion Failed: {e}")
                return False
    return False

def update_risk_engine(kite):
    """
    Runs in the background loop.
    Checks LTP vs SL/Targets for all active trades.
    """
    trades = load_trades()
    updated = False
    
    for trade in trades:
        if trade['status'] == 'OPEN':
            # 1. Get Live Price
            try:
                # For Zerodha, you need the instrument_token to fetch LTP efficiently
                # Here we use quote for simplicity (slower but easier)
                # In prod, use Websocket ticks
                quote = kite.quote(f"NFO:{trade['symbol']}")
                ltp = quote[f"NFO:{trade['symbol']}"]["last_price"]
            except:
                ltp = trade['current_ltp'] # No change if fetch fails

            trade['current_ltp'] = ltp
            
            # 2. Check Stop Loss
            if ltp <= trade['sl']:
                trade['status'] = "SL_HIT"
                # If LIVE, send Sell Order here
                updated = True
                continue

            # 3. Check Target 1 (The Safeguard)
            if ltp >= trade['targets'][0] and not trade['t1_hit']:
                trade['t1_hit'] = True
                trade['sl'] = trade['entry_price'] # Move SL to Cost
                updated = True

            # 4. Check Final Target
            if ltp >= trade['targets'][4]:
                trade['status'] = "T5_HIT"
                updated = True

    if updated:
        save_trades(trades)
