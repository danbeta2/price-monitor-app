import requests
import base64
from flask import current_app
from datetime import datetime, timedelta

class EbayService:
    AUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    
    # Token cache con expiry
    _access_token = None
    _token_expires_at = None
    _last_error = None
    
    def __init__(self):
        self.client_id = current_app.config.get('EBAY_CLIENT_ID', '')
        self.client_secret = current_app.config.get('EBAY_CLIENT_SECRET', '')
        self.marketplace = current_app.config.get('EBAY_MARKETPLACE', 'EBAY_IT')
    
    def is_configured(self):
        return bool(self.client_id and self.client_secret)
    
    def get_last_error(self):
        return EbayService._last_error
    
    def _get_access_token(self, force_refresh=False):
        """Ottiene token con caching e auto-refresh"""
        
        # Se abbiamo un token valido e non scaduto, usalo
        if not force_refresh and EbayService._access_token and EbayService._token_expires_at:
            # Refresh 5 minuti prima della scadenza
            if datetime.utcnow() < EbayService._token_expires_at - timedelta(minutes=5):
                return EbayService._access_token
            else:
                print("[eBay] Token scaduto o in scadenza, rinnovo...")
        
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
            
            EbayService._access_token = token_data.get('access_token')
            
            # eBay tokens durano 2 ore (7200 secondi)
            expires_in = token_data.get('expires_in', 7200)
            EbayService._token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            EbayService._last_error = None
            
            print(f"[eBay] Token ottenuto, scade tra {expires_in} secondi")
            return EbayService._access_token
            
        except requests.RequestException as e:
            error_msg = f"eBay auth error: {e}"
            print(error_msg)
            EbayService._last_error = error_msg
            EbayService._access_token = None
            EbayService._token_expires_at = None
            return None
    
    def search(self, query, num_results=50):
        if not self.is_configured():
            return {'error': 'eBay not configured', 'results': []}
        
        token = self._get_access_token()
        if not token:
            # Riprova una volta con force refresh
            token = self._get_access_token(force_refresh=True)
            if not token:
                return {'error': f'eBay authentication failed: {self.get_last_error()}', 'results': []}
        
        headers = {
            'Authorization': f'Bearer {token}',
            'X-EBAY-C-MARKETPLACE-ID': self.marketplace,
            'Content-Type': 'application/json',
        }
        
        params = {
            'q': query,
            'limit': min(num_results, 200),
            'filter': 'conditionIds:{1000|1500},deliveryCountry:IT',
        }
        
        try:
            response = requests.get(self.SEARCH_URL, headers=headers, params=params, timeout=30)
            
            # Se 401 Unauthorized, il token è scaduto - riprova
            if response.status_code == 401:
                print("[eBay] Token invalido, rinnovo...")
                token = self._get_access_token(force_refresh=True)
                if not token:
                    return {'error': 'eBay token refresh failed', 'results': []}
                
                headers['Authorization'] = f'Bearer {token}'
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
            
            EbayService._last_error = None
            return {
                'results': results,
                'total': len(results),
            }
            
        except requests.RequestException as e:
            error_msg = str(e)
            EbayService._last_error = error_msg
            
            # Messaggi più chiari
            if '401' in error_msg:
                error_msg = 'eBay: Token scaduto, riprova.'
            elif '403' in error_msg:
                error_msg = 'eBay: Accesso negato. Verifica credenziali.'
            elif '429' in error_msg:
                error_msg = 'eBay: Troppe richieste. Attendi qualche minuto.'
            
            return {'error': error_msg, 'results': []}
    
    def _extract_price(self, item):
        price_info = item.get('price', {})
        value = price_info.get('value')
        if value:
            try:
                return float(value)
            except ValueError:
                pass
        return None
