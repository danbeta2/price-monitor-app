import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # Database: PostgreSQL su Railway o SQLite locale
    database_url = os.getenv('DATABASE_URL', 'sqlite:///price_monitor.db')
    # Railway usa postgres:// ma SQLAlchemy vuole postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = database_url
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
    
    # Gemini AI (validazione intelligente prodotti)
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
    
    # Settings
    DEFAULT_PRICE_TOLERANCE = 50
    RESULTS_PER_SEARCH = 20
