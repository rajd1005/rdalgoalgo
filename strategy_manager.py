def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points):
    """
    Executes a trade for a specific symbol passed from the dashboard.
    """
    trades = load_trades()
    
    entry_price = 0
    if mode == "LIVE":
        try:
            # Place Order
            order_id = kite.place_order(
                tradingsymbol=specific_symbol,
                exchange=kite.EXCHANGE_NFO,
                transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=quantity,
                order_type=kite.ORDER_TYPE_MARKET,
                product=kite.PRODUCT_MIS
            )
            # Fetch Price (Simplified)
            entry_price = 100.0 
        except Exception as e:
            return {"status": "error", "message": str(e)}
    else:
        entry_price = 100.0 # Paper

    # Calculate Targets
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
