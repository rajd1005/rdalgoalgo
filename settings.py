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
    
    return {
        "exchanges": ["NSE", "NFO", "MCX", "CDS", "BSE", "BFO"],
        "watchlist": [],
        "modes": {
            "LIVE": default_mode_settings.copy(),
            "PAPER": default_mode_settings.copy()
        }
    }

def load_settings():
    defaults = get_defaults()
    try:
        setting = AppSetting.query.first()
        if setting:
            saved = json.loads(setting.data)
            
            # Integrity Check & Migration
            if "modes" not in saved:
                # Migrate old format
                old_mult = saved.get("qty_mult", 1)
                old_ratios = saved.get("ratios", [0.5, 1.0, 1.5])
                old_sl = saved.get("symbol_sl", {})
                saved["modes"] = {
                    "LIVE": {"qty_mult": old_mult, "ratios": old_ratios, "symbol_sl": old_sl.copy()},
                    "PAPER": {"qty_mult": old_mult, "ratios": old_ratios, "symbol_sl": old_sl.copy()}
                }

            # Ensure all keys exist
            for m in ["LIVE", "PAPER"]:
                if m in saved["modes"]:
                    # Default missing keys
                    for key, val in defaults["modes"][m].items():
                        if key not in saved["modes"][m]:
                            saved["modes"][m][key] = val
                            
                    # Preserve sub-dictionaries if they exist
                    if "symbol_sl" not in saved["modes"][m]:
                         saved["modes"][m]["symbol_sl"] = {}
                else:
                    saved["modes"][m] = defaults["modes"][m].copy()

            if "exchanges" not in saved: saved["exchanges"] = defaults["exchanges"]
            if "watchlist" not in saved: saved["watchlist"] = []

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
