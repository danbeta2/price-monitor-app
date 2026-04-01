import requests
from flask import current_app

class SerpAPIService:
    BASE_URL = "https://serpapi.com/search"
    
    def __init__(self):
        self.api_key = current_app.config['SERPAPI_KEY']
    
    def is_configured(self):
        return bool(self.api_key)
    
    def search(self, query, num_results=20):
        if not self.is_configured():
            return {'error': 'SerpAPI not configured', 'results': []}
        
        params = {
            'engine': 'google_shopping',
            'q': query,
            'api_key': self.api_key,
            'gl': 'it',
            'hl': 'it',
            'num': num_results,
        }
        
        try:
            response = requests.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            results = []
            shopping_results = data.get('shopping_results', [])
            
            for item in shopping_results[:num_results]:
                price = self._extract_price(item)
                if price is None:
                    continue
                
                results.append({
                    'title': item.get('title', ''),
                    'price': price,
                    'currency': 'EUR',
                    'seller_name': item.get('source', ''),
                    'seller_rating': item.get('rating'),
                    'reviews_count': item.get('reviews'),
                    'url': item.get('link', ''),
                    'image_url': item.get('thumbnail', ''),
                    'source': 'google_shopping',
                })
            
            return {
                'results': results,
                'total': len(results),
            }
            
        except requests.RequestException as e:
            return {'error': str(e), 'results': []}
    
    def _extract_price(self, item):
        price_str = item.get('extracted_price')
        if price_str is not None:
            return float(price_str)
        
        price_text = item.get('price', '')
        if not price_text:
            return None
        
        import re
        numbers = re.findall(r'[\d.,]+', price_text.replace('.', '').replace(',', '.'))
        if numbers:
            try:
                return float(numbers[0])
            except ValueError:
                pass
        
        return None
