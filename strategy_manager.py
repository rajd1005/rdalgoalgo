import json
import os
import time
from datetime import datetime

# --- FILE PERSISTENCE ---
TRADES_FILE = 'active_trades.json'

def load_trades():
    """
    Loads all trades from the JSON file.
    Returns an empty list if file doesn't exist or is corrupted.
    """
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return [] 
    return []

def save_trades(trades):
    """Saves the current list of trades to JSON."""
    with open(TRADES_FILE, 'w') as f:
        json.dump(trades, f, default=str, indent=4)

# --- HELPER: EXCHANGE DETECTION ---
def get_exchange(symbol):
    """
    Determines if the symbol belongs to NSE (Stocks) or NFO (F&O).
    """
    # 1. Derivatives (Options & Futures) always belong to NFO
    if symbol.endswith("CE") or symbol.endswith("PE") or "FUT" in symbol:
        return "NFO"
    
    # 2. Indices (Not tradable directly, but listed on NSE)
    if symbol in ["NIFTY", "BANKNIFTY", "FINNIFTY", "NIFTY 50", "NIFTY BANK"]: 
        return "NSE" 
    
    # 3. Default to NSE for Equity Stocks (e.g., RELIANCE, TATASTEEL)
    return "NSE"

# --- CORE TRADING LOGIC ---

def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points, custom_targets=None):
    """
    Executes a trade (Paper or Live) and sets up Risk Management.
    Accepts custom targets from the UI, or calculates them automatically.
    """
    trades = load_trades()
    entry_price = 0.0
    exchange_type = get_exchange(specific_symbol)
    
    # 1. EXECUTION (LIVE OR PAPER)
    if mode == "LIVE":
        try:
            # Place the Order on Zerodha
            # Note: We use MARKET order for instant execution
            order_id = kite.place_order(
                tradingsymbol=specific_symbol,
                exchange=exchange_type,
                transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=quantity,
                order_type=kite.ORDER_TYPE_MARKET,
                product=kite.PRODUCT_MIS
            )
            print(f"✅ LIVE Order Placed: {order_id}")
            
            # Fetch Entry Price
            # We fetch the immediate LTP as a proxy for execution price.
            # In a pro system, you might wait for the order callback to get exact avg_price.
            try:
                instrument_key = f"{exchange_type}:{specific_symbol}"
                quote = kite.quote(instrument_key)
                entry_price = quote[instrument_key]["last_price"]
            except:
                entry_price = 100.0 # Fallback safety if API glitches
                
        except Exception as e:
            return {"status": "error", "message": str(e)}
            
    else:
        # PAPER MODE: Fetch real price to make simulation realistic
        try:
            instrument_key = f"{exchange_type}:{specific_symbol}"
            quote = kite.quote(instrument_key)
            entry_price = quote[instrument_key]["last_price"]
        except:
            entry_price = 100.0 # Default fallback
            
    # 2. TARGET CALCULATION
    targets = []
    
    # If Dashboard sent specific targets (User Edited them), use those
    if custom_targets and len(custom_targets) >= 3:
        targets = custom_targets
        # Ensure we always have 5 targets structure (pad with logic if needed)
        while len(targets) < 5:
            targets.append(targets[-1] * 1.05) # Add 5% to last target
            
    else:
        # Auto-Calculate based on SL Risk
        # T1 = 0.5x Risk, T2 = 1x Risk, etc.
        targets = [
            entry_price + (sl_points * 0.5), # T1
            entry_price + (sl_points * 1.0), # T2
            entry_price + (sl_points * 1.5), # T3
            entry_price + (sl_points * 2.0), # T4
            entry_price + (sl_points * 3.0)  # T5
        ]

    # 3. RECORD CREATION
    trade_record = {
        "id": int(time.time()),
        "symbol": specific_symbol,
        "exchange": exchange_type,
        "mode": mode,
        "status": "OPEN",
        "entry_price": entry_price,
        "quantity": quantity,
        "sl": entry_price - sl_points, # Initial Stop Loss
        "targets": targets,
        "t1_hit": False,
        "current_ltp": entry_price
    }
    
    trades.append(trade_record)
    save_trades(trades)
    return {"status": "success", "trade": trade_record}

def promote_to_live(kite, trade_id):
    """
    Promotes a specific Paper trade to Live execution.
    Places a real market order for the existing Paper trade details.
    """
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
    Background Task: 
    1. Fetches live prices (LTP) for all open trades.
    2. Checks if Stop Loss is hit.
    3. Checks if Target 1 is hit (Moves SL to Cost).
    4. Checks if Final Target is hit.
    """
    trades = load_trades()
    updated = False
    
    for trade in trades:
        # Only check trades that are OPEN or PROMOTED_LIVE
        if trade['status'] in ['OPEN', 'PROMOTED_LIVE']:
            
            # A. Get Live Price
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
            
            # B. Check Stop Loss (SL)
            if ltp <= trade['sl']:
                trade['status'] = "SL_HIT"
                # NOTE: If this was a fully automated LIVE system, 
                # you would place a SELL order here automatically.
                continue

            # C. Check Target 1 (The Safeguard)
            # If Price hits Target 1, Move SL to Entry Price (Cost)
            if ltp >= trade['targets'][0] and not trade['t1_hit']:
                trade['t1_hit'] = True
                trade['sl'] = trade['entry_price'] 
                
            # D. Check Final Target (T5)
            if ltp >= trade['targets'][4]:
                trade['status'] = "T5_HIT"

    if updated:
        save_trades(trades)
