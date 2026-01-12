from flask_sqlalchemy import SQLAlchemy
import json

db = SQLAlchemy()

class AppSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text, nullable=False) # Stores JSON string

class ActiveTrade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # We keep the original timestamp-based ID logic as a reference for the frontend
    trade_ref = db.Column(db.String(50), unique=True, nullable=False) 
    
    symbol = db.Column(db.String(50), nullable=False)
    exchange = db.Column(db.String(20), nullable=False)
    mode = db.Column(db.String(10), nullable=False) # LIVE / PAPER
    status = db.Column(db.String(20), nullable=False) # OPEN, PENDING, etc.
    order_type = db.Column(db.String(20), default="MARKET")
    
    # Price & Quantity
    entry_price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    lot_size = db.Column(db.Integer, default=1)
    
    # Live Monitoring
    current_ltp = db.Column(db.Float, default=0.0)
    highest_ltp = db.Column(db.Float, default=0.0)
    made_high = db.Column(db.Float, default=0.0)
    
    # Protection
    sl = db.Column(db.Float, nullable=False)
    trailing_sl = db.Column(db.Float, default=0.0)
    sl_to_entry = db.Column(db.Integer, default=0)
    exit_multiplier = db.Column(db.Integer, default=1)
    
    # Complex Data Stored as JSON Strings
    targets_json = db.Column(db.Text, default="[]")
    target_controls_json = db.Column(db.Text, default="[]")
    targets_hit_indices_json = db.Column(db.Text, default="[]")
    logs_json = db.Column(db.Text, default="[]")
    
    # Metadata
    trigger_dir = db.Column(db.String(10), nullable=True)
    entry_time = db.Column(db.String(30))

    def to_dict(self):
        """Convert DB Object to Dictionary for Frontend Compatibility"""
        return {
            "id": int(self.trade_ref), # Return as int to match old frontend logic
            "symbol": self.symbol,
            "exchange": self.exchange,
            "mode": self.mode,
            "status": self.status,
            "order_type": self.order_type,
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "lot_size": self.lot_size,
            "current_ltp": self.current_ltp,
            "highest_ltp": self.highest_ltp,
            "made_high": self.made_high,
            "sl": self.sl,
            "trailing_sl": self.trailing_sl,
            "sl_to_entry": self.sl_to_entry,
            "exit_multiplier": self.exit_multiplier,
            "targets": json.loads(self.targets_json),
            "target_controls": json.loads(self.target_controls_json),
            "targets_hit_indices": json.loads(self.targets_hit_indices_json),
            "logs": json.loads(self.logs_json),
            "trigger_dir": self.trigger_dir,
            "entry_time": self.entry_time
        }

class TradeHistory(db.Model):
    # BigInteger to handle timestamp IDs safely
    id = db.Column(db.BigInteger, primary_key=True)
    data = db.Column(db.Text, nullable=False) # Keeping History as JSON for simplicity
