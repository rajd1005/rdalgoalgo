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

# --- HELPER: EXCHANGE DETECTION ---
def get_exchange(symbol):
    """
    Determines if the symbol belongs to NSE (Stocks) or NFO (F&O).
    Logic: options/futures usually end with CE/PE/FUT or have specific naming formats.
    """
    if symbol.endswith("CE") or symbol.endswith("PE") or "FUT" in symbol:
        return "NFO"
    # Basic check: NIFTY/BANKNIFTY are indices, but if passed as pure symbol without suffix, handle carefully
    if symbol in ["NIFTY", "BANKNIFTY"]: 
        return "NSE" 
    # Default to NSE for normal stocks like RELIANCE, INFY
    return "NSE"

# --- TRADING LOGIC ---

def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points):
    """
    Executes a trade (Paper or Live) for a specific symbol passed from the dashboard.
    """
    trades = load_trades()
    entry_price = 0.0
    exchange_type = get_exchange(specific_symbol)
    
    # 1. EXECUTION (LIVE OR PAPER)
    if mode == "LIVE":
        try:
            # Place the Order on Zerodha
            # Note: kite.EXCHANGE_NFO is a string "NFO", kite.EXCHANGE_NSE is "NSE"
            order_id = kite.place_order(
                tradingsymbol=specific_symbol,
                exchange=exchange_type,
                transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=quantity,
                order_type=kite.ORDER_TYPE_MARKET,
                product=kite.PRODUCT_MIS
            )
            print(f"✅ LIVE Order Placed: {order_id}")
            
            # Fetch Entry Price immediately for record keeping
            # In a high-speed system, you would wait for order update via WebSocket.
            # Here we fetch the current LTP as a proxy for the entry price.
            try:
                instrument_key = f"{exchange_type}:{specific_symbol}"
                quote = kite.quote(instrument_key)
                entry_price = quote[instrument_key]["last_price"]
            except:
                entry_price = 100.0 # Fallback safety
                
        except Exception as e:
            return {"status": "error", "message": str(e)}
    else:
        # PAPER MODE: Fetch real price to make simulation realistic
        try:
            instrument_key = f"{exchange_type}:{specific_symbol}"
            quote = kite.quote(instrument_key)
            entry_price = quote[instrument_key]["last_price"]
        except:
            entry_price = 100.0 # Default fallback if API fails
            
    # 2. RISK CALCULATION (5 TARGETS)
    # Target 1: 0.5x Risk (Safe Exit)
    # Target 5: 3.0x Risk (Moonshot)
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
        "exchange": exchange_type,
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
                    exchange=trade.get('exchange', 'NFO'), # Default to NFO if missing
                    transaction_type=kite.TRANSACTION_TYPE_BUY,
                    quantity=trade['quantity'],
                    order_type=kite.ORDER_TYPE_MARKET,
                    product=kite.PRODUCT_MIS
                )
                
                # Update State
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
        # Only check trades that are OPEN or LIVE
        if trade['status'] in ['OPEN', 'PROMOTED_LIVE']:
            
            # 1. Get Live Price
            exchange = trade.get('exchange', 'NFO')
            instrument_key = f"{exchange}:{trade['symbol']}"
            
            try:
                quote = kite.quote(instrument_key)
                ltp = quote[instrument_key]["last_price"]
            except Exception:
                # If API fails or network issue, skip update this cycle
                continue

            trade['current_ltp'] = ltp
            updated = True
            
            # 2. Check Stop Loss (SL)
            if ltp <= trade['sl']:
                trade['status'] = "SL_HIT"
                # NOTE: If this was a LIVE trade, you would place a SELL order here automatically.
                # Example: kite.place_order(transaction_type=kite.TRANSACTION_TYPE_SELL, ...)
                continue

            # 3. Check Target 1 (The Safeguard)
            # If Price hits Target 1, Move SL to Entry Price (Cost)
            if ltp >= trade['targets'][0] and not trade['t1_hit']:
                trade['t1_hit'] = True
                trade['sl'] = trade['entry_price'] 
                
            # 4. Check Final Target (T5)
            if ltp >= trade['targets'][4]:
                trade['status'] = "T5_HIT"
                # NOTE: If LIVE, place SELL order here.

    if updated:
        save_trades(trades)
