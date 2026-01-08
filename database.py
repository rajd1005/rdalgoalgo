from flask_sqlalchemy import SQLAlchemy
import json

db = SQLAlchemy()

class AppSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text, nullable=False) # Stores JSON string

class ActiveTrade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text, nullable=False) # Stores JSON string

class TradeHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text, nullable=False) # Stores JSON string
