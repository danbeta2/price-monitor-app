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
        """Ricerca su Google Shopping"""
        return self._search_engine('google_shopping', query, num_results)
    
    def search_web(self, query, num_results=30):
        """Ricerca su Google Web - trova prezzi da siti e-commerce"""
        return self._search_engine('google', query, num_results)
    
    def _search_engine(self, engine, query, num_results):
        if not self.is_configured():
            return {'error': 'SerpAPI not configured', 'results': []}
        
        # Check crediti prima della ricerca
        remaining = self.get_remaining_searches()
        if remaining is not None and remaining <= 0:
            return {'error': 'Crediti SerpAPI esauriti! Upgrade il piano o attendi il prossimo mese.', 'results': []}
        
        params = {
            'engine': engine,
            'q': query + ' prezzo €' if engine == 'google' else query,
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
            
            if engine == 'google_shopping':
                results = self._parse_shopping_results(data, num_results)
            else:
                results = self._parse_web_results(data, num_results)
            
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
    
    def _parse_shopping_results(self, data, num_results):
        """Parsing risultati Google Shopping"""
        results = []
        shopping_results = data.get('shopping_results', [])
        
        for item in shopping_results[:num_results]:
            price = self._extract_price(item)
            if price is None:
                continue

            # Google Shopping puo avere l'URL in diversi campi
            url = item.get('link') or item.get('product_link') or ''

            results.append({
                'title': item.get('title', ''),
                'price': price,
                'currency': 'EUR',
                'seller_name': item.get('source', ''),
                'seller_rating': item.get('rating'),
                'reviews_count': item.get('reviews'),
                'url': url,
                'image_url': item.get('thumbnail', ''),
                'source': 'google_shopping',
            })
        
        return results
    
    def _parse_web_results(self, data, num_results):
        """Parsing risultati Google Web - estrae prezzi dai rich snippets e titoli"""
        import re
        results = []
        
        organic_results = data.get('organic_results', [])
        
        for item in organic_results[:num_results]:
            title = item.get('title', '')
            snippet = item.get('snippet', '')
            link = item.get('link', '')
            
            # Estrai prezzo da titolo, snippet o rich snippet
            price = None
            
            # Check rich snippet price
            if item.get('rich_snippet') and item['rich_snippet'].get('top', {}).get('detected_extensions', {}).get('price'):
                price = item['rich_snippet']['top']['detected_extensions']['price']
            
            # Check price in snippet
            if not price:
                price_match = re.search(r'€\s*(\d+[.,]?\d*)', snippet)
                if price_match:
                    price = self._parse_price_string(price_match.group(1))
            
            # Check price in title
            if not price:
                price_match = re.search(r'€\s*(\d+[.,]?\d*)', title)
                if price_match:
                    price = self._parse_price_string(price_match.group(1))
            
            # Skip se non ha prezzo
            if price is None or price <= 0:
                continue
            
            # Estrai nome venditore dal dominio
            domain = ''
            if link:
                domain_match = re.search(r'https?://(?:www\.)?([^/]+)', link)
                if domain_match:
                    domain = domain_match.group(1)
            
            results.append({
                'title': title,
                'price': price,
                'currency': 'EUR',
                'seller_name': domain,
                'seller_rating': None,
                'reviews_count': None,
                'url': link,
                'image_url': item.get('thumbnail', ''),
                'source': 'google_web',
            })
        
        return results
    
    def _parse_price_string(self, price_str):
        """Converte stringa prezzo in float"""
        try:
            # Rimuovi punti separatori migliaia, converti virgola in punto
            clean = price_str.replace('.', '').replace(',', '.')
            return float(clean)
        except:
            return None
    
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
