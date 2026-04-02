import requests
from flask import current_app
from datetime import datetime

class SerpAPIService:
    BASE_URL = "https://serpapi.com/search"
    ACCOUNT_URL = "https://serpapi.com/account"
    
    # Tracking crediti (in memoria, reset al restart)
    _searches_this_session = 0
    _last_account_check = None
    _account_info = None
    
    def __init__(self):
        self.api_key = current_app.config.get('SERPAPI_KEY', '')
    
    def is_configured(self):
        return bool(self.api_key)
    
    def get_account_info(self, force_refresh=False):
        """Ottiene info account SerpAPI (crediti rimanenti, piano, etc.)"""
        if not self.is_configured():
            return None
        
        # Cache per 5 minuti
        if not force_refresh and self._account_info and self._last_account_check:
            from datetime import timedelta
            if datetime.utcnow() - self._last_account_check < timedelta(minutes=5):
                return self._account_info
        
        try:
            response = requests.get(
                self.ACCOUNT_URL,
                params={'api_key': self.api_key},
                timeout=10
            )
            response.raise_for_status()
            self._account_info = response.json()
            self._last_account_check = datetime.utcnow()
            return self._account_info
        except Exception as e:
            print(f"[SerpAPI] Error fetching account info: {e}")
            return None
    
    def get_remaining_searches(self):
        """Ritorna le ricerche rimanenti questo mese"""
        info = self.get_account_info()
        if not info:
            return None
        
        plan_limit = info.get('plan_searches_left', info.get('searches_per_month', 100))
        return plan_limit
    
    def get_usage_warning(self):
        """Ritorna un warning se i crediti sono bassi"""
        remaining = self.get_remaining_searches()
        if remaining is None:
            return None
        
        if remaining <= 0:
            return {'level': 'critical', 'message': f'Crediti SerpAPI esauriti!'}
        elif remaining <= 10:
            return {'level': 'danger', 'message': f'Solo {remaining} ricerche SerpAPI rimanenti!'}
        elif remaining <= 50:
            return {'level': 'warning', 'message': f'{remaining} ricerche SerpAPI rimanenti'}
        
        return None
    
    def search(self, query, num_results=50):
        if not self.is_configured():
            return {'error': 'SerpAPI not configured', 'results': []}
        
        # Check crediti prima della ricerca
        remaining = self.get_remaining_searches()
        if remaining is not None and remaining <= 0:
            return {'error': 'Crediti SerpAPI esauriti! Upgrade il piano o attendi il prossimo mese.', 'results': []}
        
        params = {
            'engine': 'google_shopping',
            'q': query,
            'api_key': self.api_key,
            'gl': 'it',
            'hl': 'it',
            'num': min(num_results, 100),
        }
        
        try:
            response = requests.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Incrementa counter sessione
            SerpAPIService._searches_this_session += 1
            
            # Invalida cache account info (crediti cambiati)
            SerpAPIService._last_account_check = None
            
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
                'searches_this_session': SerpAPIService._searches_this_session,
            }
            
        except requests.RequestException as e:
            error_msg = str(e)
            if '429' in error_msg:
                error_msg = 'Rate limit SerpAPI raggiunto. Riprova tra qualche minuto.'
            return {'error': error_msg, 'results': []}
    
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
