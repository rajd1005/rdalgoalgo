from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class AppSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text, nullable=False) # Stores JSON string

class ActiveTrade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text, nullable=False) # Stores JSON string

class TradeHistory(db.Model):
    # BigInteger to handle timestamp IDs safely
    id = db.Column(db.BigInteger, primary_key=True)
    data = db.Column(db.Text, nullable=False) # Stores JSON string
