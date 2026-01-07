import json
import os
import time
from datetime import datetime

TRADES_FILE = 'active_trades.json'

def load_trades():
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, 'r') as f: return json.load(f)
        except: return []
    return []

def save_trades(trades):
    with open(TRADES_FILE, 'w') as f: json.dump(trades, f, default=str, indent=4)

def get_exchange(symbol):
    if symbol.endswith("CE") or symbol.endswith("PE") or "FUT" in symbol: return "NFO"
    if symbol in ["NIFTY", "BANKNIFTY", "FINNIFTY", "NIFTY 50", "NIFTY BANK"]: return "NSE"
    return "NSE"

def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points, custom_targets, order_type, limit_price=0):
    trades = load_trades()
    entry_price = 0.0
    exchange_type = get_exchange(specific_symbol)
    
    # EXECUTION
    if mode == "LIVE":
        try:
            kite_order_type = kite.ORDER_TYPE_MARKET if order_type == "MARKET" else kite.ORDER_TYPE_LIMIT
            price = 0 if order_type == "MARKET" else limit_price
            
            order_id = kite.place_order(
                tradingsymbol=specific_symbol,
                exchange=exchange_type,
                transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=quantity,
                order_type=kite_order_type,
                price=price,
                product=kite.PRODUCT_MIS
            )
            print(f"✅ LIVE Order: {order_id}")
            
            # If Limit order, entry price is the limit price
            if order_type == "LIMIT":
                entry_price = float(limit_price)
            else:
                try:
                    quote = kite.quote(f"{exchange_type}:{specific_symbol}")
                    entry_price = quote[f"{exchange_type}:{specific_symbol}"]["last_price"]
                except:
                    entry_price = 100.0
        except Exception as e:
            return {"status": "error", "message": str(e)}
    else:
        # Paper
        if order_type == "LIMIT":
             entry_price = float(limit_price)
        else:
            try:
                quote = kite.quote(f"{exchange_type}:{specific_symbol}")
                entry_price = quote[f"{exchange_type}:{specific_symbol}"]["last_price"]
            except:
                entry_price = 100.0

    # TARGETS
    targets = []
    if custom_targets and len(custom_targets) >= 3:
        targets = custom_targets
        while len(targets) < 5: targets.append(targets[-1] * 1.05)
    else:
        # Auto Calc if UI didn't send them (Fallback)
        targets = [
            entry_price + (sl_points * 0.5),
            entry_price + (sl_points * 1.0),
            entry_price + (sl_points * 1.5),
            entry_price + (sl_points * 2.0),
            entry_price + (sl_points * 3.0)
        ]

    trade_record = {
        "id": int(time.time()),
        "symbol": specific_symbol,
        "exchange": exchange_type,
        "mode": mode,
        "order_type": order_type,
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
    trades = load_trades()
    for trade in trades:
        if trade['id'] == int(trade_id) and trade['mode'] == "PAPER":
            try:
                kite.place_order(
                    tradingsymbol=trade['symbol'],
                    exchange=trade.get('exchange', 'NFO'),
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
    trades = load_trades()
    updated = False
    
    for trade in trades:
        if trade['status'] in ['OPEN', 'PROMOTED_LIVE']:
            exchange = trade.get('exchange', 'NFO')
            try:
                quote = kite.quote(f"{exchange}:{trade['symbol']}")
                ltp = quote[f"{exchange}:{trade['symbol']}"]["last_price"]
            except: continue

            trade['current_ltp'] = ltp
            updated = True
            
            if ltp <= trade['sl']: trade['status'] = "SL_HIT"
            if ltp >= trade['targets'][0] and not trade['t1_hit']:
                trade['t1_hit'] = True
                trade['sl'] = trade['entry_price'] 
            if ltp >= trade['targets'][4]: trade['status'] = "T5_HIT"

    if updated: save_trades(trades)
