import requests
import base64
from flask import current_app

class EbayService:
    AUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    
    def __init__(self):
        self.client_id = current_app.config['EBAY_CLIENT_ID']
        self.client_secret = current_app.config['EBAY_CLIENT_SECRET']
        self.marketplace = current_app.config['EBAY_MARKETPLACE']
        self._access_token = None
    
    def is_configured(self):
        return bool(self.client_id and self.client_secret)
    
    def _get_access_token(self):
        if self._access_token:
            return self._access_token
        
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {encoded_credentials}',
        }
        
        data = {
            'grant_type': 'client_credentials',
            'scope': 'https://api.ebay.com/oauth/api_scope',
        }
        
        try:
            response = requests.post(self.AUTH_URL, headers=headers, data=data, timeout=30)
            response.raise_for_status()
            token_data = response.json()
            self._access_token = token_data.get('access_token')
            return self._access_token
        except requests.RequestException as e:
            print(f"eBay auth error: {e}")
            return None
    
    def search(self, query, num_results=50):
        if not self.is_configured():
            return {'error': 'eBay not configured', 'results': []}
        
        token = self._get_access_token()
        if not token:
            return {'error': 'Failed to authenticate with eBay', 'results': []}
        
        headers = {
            'Authorization': f'Bearer {token}',
            'X-EBAY-C-MARKETPLACE-ID': self.marketplace,
            'Content-Type': 'application/json',
        }
        
        # conditionIds: 1000=New, 1500=New other, 2000=Certified refurb, 2500=Seller refurb, 3000=Used
        # deliveryCountry: filtra per spedizione in Italia
        params = {
            'q': query,
            'limit': min(num_results, 200),  # Max 200 per eBay
            'filter': 'conditionIds:{1000|1500},deliveryCountry:IT',
        }
        
        try:
            response = requests.get(self.SEARCH_URL, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            results = []
            items = data.get('itemSummaries', [])
            
            for item in items[:num_results]:
                price = self._extract_price(item)
                if price is None:
                    continue
                
                results.append({
                    'title': item.get('title', ''),
                    'price': price,
                    'currency': 'EUR',
                    'seller_name': item.get('seller', {}).get('username', ''),
                    'seller_rating': item.get('seller', {}).get('feedbackPercentage'),
                    'url': item.get('itemWebUrl', ''),
                    'image_url': item.get('image', {}).get('imageUrl', ''),
                    'source': 'ebay',
                    'condition': item.get('condition', ''),
                })
            
            return {
                'results': results,
                'total': len(results),
            }
            
        except requests.RequestException as e:
            return {'error': str(e), 'results': []}
    
    def _extract_price(self, item):
        price_info = item.get('price', {})
        value = price_info.get('value')
        if value:
            try:
                return float(value)
            except ValueError:
                pass
        return None
