import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///price_monitor.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # WooCommerce
    WC_URL = os.getenv('WC_URL', '')
    WC_CONSUMER_KEY = os.getenv('WC_CONSUMER_KEY', '')
    WC_CONSUMER_SECRET = os.getenv('WC_CONSUMER_SECRET', '')
    
    # SerpAPI
    SERPAPI_KEY = os.getenv('SERPAPI_KEY', '')
    
    # eBay
    EBAY_CLIENT_ID = os.getenv('EBAY_CLIENT_ID', '')
    EBAY_CLIENT_SECRET = os.getenv('EBAY_CLIENT_SECRET', '')
    EBAY_MARKETPLACE = os.getenv('EBAY_MARKETPLACE', 'EBAY_IT')
    
    # Settings
    DEFAULT_PRICE_TOLERANCE = 50
    RESULTS_PER_SEARCH = 20
