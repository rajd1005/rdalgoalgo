import json
from database import db, AppSetting

def get_defaults():
    # Define default settings for a mode
    default_mode_settings = {
        "qty_mult": 1, 
        "ratios": [0.5, 1.0, 1.5], 
        "symbol_sl": {}, 
        "trailing_sl": 0,
        "sl_to_entry": 0,
        "order_type": "MARKET",
        "exit_multiplier": 1
    }
    
    # Default Telegram Templates
    tg_templates = {
        "TRADE_ADDED": "🆕 <b>NEW TRADE: {symbol}</b> ({mode})\n🔹 Entry: {entry}\n🔻 SL: {sl}\n🎯 Targets: {targets}\n📦 Qty: {qty}",
        "TRADE_UPDATE": "📝 <b>UPDATE: {symbol}</b>\nNew SL: {sl}\nNew Targets: {targets}",
        "TRADE_ACTIVATED": "⚡ <b>ACTIVATED: {symbol}</b>\nPrice: {ltp}",
        "TARGET_HIT": "🎯 <b>TARGET {index} HIT: {symbol}</b>\nPrice: {ltp}\n💰 P&L: ₹ {pnl}",
        "MADE_HIGH": "📈 <b>NEW HIGH: {symbol}</b>\nHigh: {high}",
        "CLOSE_SUMMARY": "🏁 <b>CLOSED: {symbol}</b>\nExit Price: {ltp}\n🏆 High: {high}\n💵 Final P&L: ₹ {pnl}"
    }

    return {
        "exchanges": ["NSE", "NFO", "MCX", "CDS", "BSE", "BFO"],
        "watchlist": [],
        "modes": {
            "LIVE": default_mode_settings.copy(),
            "PAPER": default_mode_settings.copy(),
            "SIMULATOR": default_mode_settings.copy()
        },
        "telegram": {
            "enabled": False,
            "bot_token": "",
            "channels": [], # List of {name, chat_id, limit}
            "forwarding_rules": [], # List of {source_id, dest_id, trigger_event, delay}
            "events": {
                "TRADE_ADDED": True,
                "TRADE_UPDATE": True,
                "TRADE_ACTIVATED": True,
                "TARGET_HIT": True,
                "MADE_HIGH": True,
                "CLOSE_SUMMARY": True
            },
            "templates": tg_templates
        }
    }

def load_settings():
    defaults = get_defaults()
    try:
        setting = AppSetting.query.first()
        if setting:
            saved = json.loads(setting.data)
            
            # Integrity Check & Migration for Modes
            if "modes" not in saved:
                old_mult = saved.get("qty_mult", 1)
                old_ratios = saved.get("ratios", [0.5, 1.0, 1.5])
                old_sl = saved.get("symbol_sl", {})
                saved["modes"] = {
                    "LIVE": {"qty_mult": old_mult, "ratios": old_ratios, "symbol_sl": old_sl.copy()},
                    "PAPER": {"qty_mult": old_mult, "ratios": old_ratios, "symbol_sl": old_sl.copy()},
                    "SIMULATOR": {"qty_mult": old_mult, "ratios": old_ratios, "symbol_sl": old_sl.copy()}
                }

            # Ensure all keys exist for modes
            for m in ["LIVE", "PAPER", "SIMULATOR"]:
                if m in saved["modes"]:
                    for key, val in defaults["modes"][m].items():
                        if key not in saved["modes"][m]:
                            saved["modes"][m][key] = val
                    if "symbol_sl" not in saved["modes"][m]:
                         saved["modes"][m]["symbol_sl"] = {}
                else:
                    saved["modes"][m] = defaults["modes"][m].copy()

            if "exchanges" not in saved: saved["exchanges"] = defaults["exchanges"]
            if "watchlist" not in saved: saved["watchlist"] = []
            
            # Telegram Migration
            if "telegram" not in saved:
                saved["telegram"] = defaults["telegram"]
            else:
                # Merge deep keys for telegram
                for k, v in defaults["telegram"].items():
                    if k not in saved["telegram"]: saved["telegram"][k] = v
                for k, v in defaults["telegram"]["events"].items():
                    if k not in saved["telegram"]["events"]: saved["telegram"]["events"][k] = v
                for k, v in defaults["telegram"]["templates"].items():
                    if k not in saved["telegram"]["templates"]: saved["telegram"]["templates"][k] = v
                
                if "channels" not in saved["telegram"]:
                    saved["telegram"]["channels"] = []
                    if saved["telegram"].get("chat_id"):
                        saved["telegram"]["channels"].append({
                            "name": "Default Channel",
                            "chat_id": saved["telegram"]["chat_id"],
                            "limit": 100
                        })
                
                # Forwarding Migration
                if "forwarding_rules" not in saved["telegram"]:
                    saved["telegram"]["forwarding_rules"] = []

            return saved
    except Exception as e:
        print(f"Error loading settings: {e}")
    
    return defaults

def save_settings_file(data):
    try:
        setting = AppSetting.query.first()
        if not setting:
            setting = AppSetting(data=json.dumps(data))
            db.session.add(setting)
        else:
            setting.data = json.dumps(data)
        db.session.commit()
        return True
    except Exception as e:
        print(f"Settings Save Error: {e}")
        db.session.rollback()
        return False
