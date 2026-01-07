import json
import os
import time
from datetime import datetime

# --- FILE PERSISTENCE ---
TRADES_FILE = 'active_trades.json'

def load_trades():
    """Loads all trades from the JSON file."""
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return [] # Return empty list if file is corrupted
    return []

def save_trades(trades):
    """Saves the current list of trades to JSON."""
    with open(TRADES_FILE, 'w') as f:
        json.dump(trades, f, default=str, indent=4)

# --- TRADING LOGIC ---

def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points):
    """
    Executes a trade (Paper or Live) for a specific symbol passed from the dashboard.
    """
    trades = load_trades()
    
    entry_price = 0.0
    
    if mode == "LIVE":
        try:
            # 1. Place the Order on Zerodha
            order_id = kite.place_order(
                tradingsymbol=specific_symbol,
                exchange=kite.EXCHANGE_NFO,
                transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=quantity,
                order_type=kite.ORDER_TYPE_MARKET,
                product=kite.PRODUCT_MIS
            )
            print(f"✅ LIVE Order Placed: {order_id}")
            
            # 2. Fetch Entry Price (Simplified: getting LTP immediately)
            # In production, you might want to fetch the actual average execution price
            try:
                quote = kite.quote(f"NFO:{specific_symbol}")
                entry_price = quote[f"NFO:{specific_symbol}"]["last_price"]
            except:
                entry_price = 100.0 # Fallback if fetch fails quickly
                
        except Exception as e:
            return {"status": "error", "message": str(e)}
    else:
        # PAPER MODE: Fetch real price to make simulation realistic
        try:
            quote = kite.quote(f"NFO:{specific_symbol}")
            entry_price = quote[f"NFO:{specific_symbol}"]["last_price"]
        except:
            entry_price = 100.0 # Default fallback
            
    # Calculate Risk Targets
    targets = [
        entry_price + (sl_points * 0.5), # T1
        entry_price + (sl_points * 1.0), # T2
        entry_price + (sl_points * 1.5), # T3
        entry_price + (sl_points * 2.0), # T4
        entry_price + (sl_points * 3.0)  # T5
    ]

    trade_record = {
        "id": int(time.time()),
        "symbol": specific_symbol,
        "mode": mode,
        "status": "OPEN",
        "entry_price": entry_price,
        "quantity": quantity,
        "sl": entry_price - sl_points,
        "targets": targets,
        "t1_hit": False,
        "current_ltp": entry_price
    }
    
    trades.append(trade_record)
    save_trades(trades)
    return {"status": "success", "trade": trade_record}

def promote_to_live(kite, trade_id):
    """Promotes a specific Paper trade to Live execution."""
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
                trade['status'] = "PROMOTED_LIVE" 
                save_trades(trades)
                return True
            except Exception as e:
                print(f"Promotion Failed: {e}")
                return False
    return False

def update_risk_engine(kite):
    """
    Background Task: Updates LTP and checks SL/Targets for all active trades.
    """
    trades = load_trades()
    updated = False
    
    for trade in trades:
        if trade['status'] in ['OPEN', 'PROMOTED_LIVE']:
            # 1. Get Live Price
            try:
                quote = kite.quote(f"NFO:{trade['symbol']}")
                ltp = quote[f"NFO:{trade['symbol']}"]["last_price"]
            except Exception:
                # If API fails, skip update this cycle
                continue

            trade['current_ltp'] = ltp
            updated = True
            
            # 2. Check Stop Loss
            if ltp <= trade['sl']:
                trade['status'] = "SL_HIT"
                # If LIVE, you would place a SELL order here
                continue

            # 3. Check Target 1 (The Safeguard)
            if ltp >= trade['targets'][0] and not trade['t1_hit']:
                trade['t1_hit'] = True
                trade['sl'] = trade['entry_price'] # Move SL to Cost
                
            # 4. Check Final Target
            if ltp >= trade['targets'][4]:
                trade['status'] = "T5_HIT"

    if updated:
        save_trades(trades)
