# backend/config.py
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG_PATH = os.environ.get("CONFIG_PATH", os.path.join(BASE_DIR, "config", "exchange_config.json"))
DEFAULT_CONFIG_PATH = os.environ.get("DEFAULT_CONFIG_PATH", os.path.join(BASE_DIR, "default_exchange_config.json"))
STATIC_DIR  = os.environ.get("STATIC_DIR", os.path.join(BASE_DIR, "static"))
EARNINGS_DIR = os.path.join(STATIC_DIR, "earnings")
UPLOADS_DIR  = os.path.join(STATIC_DIR, "uploads")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(EARNINGS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

BAR_PRICE_PATH = os.path.join(STATIC_DIR, "bar_prices.json")

