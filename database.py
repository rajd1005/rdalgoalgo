from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# --- RESTORED AppSetting ---
class AppSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text, nullable=False) # Stores JSON string

class ActiveTrade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text, nullable=False) # Stores JSON string

class TradeHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text, nullable=False) # Stores JSON string

class TradeNotification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime)
    mode = db.Column(db.String(20))   # 'LIVE' or 'PAPER'
    symbol = db.Column(db.String(50))
    message = db.Column(db.String(500))
    trade_id = db.Column(db.String(50))

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": self.mode,
            "symbol": self.symbol,
            "message": self.message,
            "trade_id": self.trade_id
        }
