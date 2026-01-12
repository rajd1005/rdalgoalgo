from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
import json
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='USER')  # 'ADMIN' or 'USER'
    
    # Subscription & Security
    plan = db.Column(db.String(20), default='TRIAL') # 'TRIAL', 'MONTHLY', 'YEARLY'
    plan_expiry = db.Column(db.DateTime, nullable=True)
    session_token = db.Column(db.String(100), nullable=True) # For Single Device Login
    
    # User's Own Broker Credentials
    broker_api_key = db.Column(db.String(100), nullable=True)
    broker_api_secret = db.Column(db.String(100), nullable=True)
    broker_access_token = db.Column(db.String(200), nullable=True)
    broker_login_date = db.Column(db.String(20), nullable=True) # YYYY-MM-DD to check freshness

class AppSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text, nullable=False) # JSON: Admin's global settings

class ActiveTrade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # Linked to User
    
    trade_ref = db.Column(db.String(50), unique=True, nullable=False) 
    symbol = db.Column(db.String(50), nullable=False)
    exchange = db.Column(db.String(20), nullable=False)
    mode = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    order_type = db.Column(db.String(20), default="MARKET")
    
    entry_price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    lot_size = db.Column(db.Integer, default=1)
    
    current_ltp = db.Column(db.Float, default=0.0)
    highest_ltp = db.Column(db.Float, default=0.0)
    made_high = db.Column(db.Float, default=0.0)
    
    sl = db.Column(db.Float, nullable=False)
    trailing_sl = db.Column(db.Float, default=0.0)
    sl_to_entry = db.Column(db.Integer, default=0)
    exit_multiplier = db.Column(db.Integer, default=1)
    
    targets_json = db.Column(db.Text, default="[]")
    target_controls_json = db.Column(db.Text, default="[]")
    targets_hit_indices_json = db.Column(db.Text, default="[]")
    logs_json = db.Column(db.Text, default="[]")
    
    trigger_dir = db.Column(db.String(10), nullable=True)
    entry_time = db.Column(db.String(30))

    def to_dict(self):
        return {
            "id": int(self.trade_ref),
            "user_id": self.user_id,
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
    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # Linked to User
    data = db.Column(db.Text, nullable=False)
