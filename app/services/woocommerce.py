import requests
from requests.auth import HTTPBasicAuth
from flask import current_app

class WooCommerceService:
    
    def __init__(self):
        self.base_url = current_app.config.get('WC_URL', '')
        self.consumer_key = current_app.config.get('WC_CONSUMER_KEY', '')
        self.consumer_secret = current_app.config.get('WC_CONSUMER_SECRET', '')
        self.last_error = None
    
    def is_configured(self):
        return bool(self.base_url and self.consumer_key and self.consumer_secret)
    
    def _request(self, endpoint, params=None):
        if not self.is_configured():
            self.last_error = "WooCommerce non configurato. Verifica WC_URL, WC_CONSUMER_KEY e WC_CONSUMER_SECRET"
            print(self.last_error)
            return None
            
        url = f"{self.base_url}/wp-json/wc/v3/{endpoint}"
        auth = HTTPBasicAuth(self.consumer_key, self.consumer_secret)
        
        print(f"[WooCommerce] Requesting: {url}")
        
        try:
            response = requests.get(url, auth=auth, params=params, timeout=30)
            print(f"[WooCommerce] Response status: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            print(f"[WooCommerce] Got {len(data) if isinstance(data, list) else 1} items")
            return data
        except requests.RequestException as e:
            self.last_error = str(e)
            print(f"[WooCommerce] API error: {e}")
            return None
    
    def get_products(self, page=1, per_page=20, category=None, search=None, in_stock_only=False):
        params = {
            'page': page,
            'per_page': per_page,
            'status': 'publish',
            'orderby': 'title',
            'order': 'asc',
        }
        
        if category:
            params['category'] = category
        if search:
            params['search'] = search
        if in_stock_only:
            params['stock_status'] = 'instock'
        
        return self._request('products', params) or []
    
    def get_product(self, product_id):
        return self._request(f'products/{product_id}')
    
    def get_categories(self):
        params = {
            'per_page': 100,
            'hide_empty': True,
        }
        return self._request('products/categories', params) or []
    
    def get_total_products(self):
        url = f"{self.base_url}/wp-json/wc/v3/products"
        auth = HTTPBasicAuth(self.consumer_key, self.consumer_secret)
        
        try:
            response = requests.get(url, auth=auth, params={'per_page': 1}, timeout=30)
            return int(response.headers.get('X-WP-Total', 0))
        except:
            return 0
