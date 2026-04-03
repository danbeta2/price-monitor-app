import requests
import base64
import re
from flask import current_app
from datetime import datetime, timedelta

class EbayService:
    AUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    # Marketplace da cercare in ordine di priorità
    MARKETPLACES = ['EBAY_IT', 'EBAY_DE', 'EBAY_FR', 'EBAY_ES']

    # Token cache con expiry
    _access_token = None
    _token_expires_at = None
    _last_error = None

    def __init__(self):
        self.client_id = current_app.config.get('EBAY_CLIENT_ID', '')
        self.client_secret = current_app.config.get('EBAY_CLIENT_SECRET', '')
        self.primary_marketplace = current_app.config.get('EBAY_MARKETPLACE', 'EBAY_IT')

    def is_configured(self):
        return bool(self.client_id and self.client_secret)

    def get_last_error(self):
        return EbayService._last_error

    def _get_access_token(self, force_refresh=False):
        """Ottiene token con caching e auto-refresh"""
        if not force_refresh and EbayService._access_token and EbayService._token_expires_at:
            if datetime.utcnow() < EbayService._token_expires_at - timedelta(minutes=5):
                return EbayService._access_token

        credentials = f"{self.client_id}:{self.client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        try:
            response = requests.post(self.AUTH_URL, headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'Authorization': f'Basic {encoded_credentials}',
            }, data={
                'grant_type': 'client_credentials',
                'scope': 'https://api.ebay.com/oauth/api_scope',
            }, timeout=30)
            response.raise_for_status()
            token_data = response.json()

            EbayService._access_token = token_data.get('access_token')
            expires_in = token_data.get('expires_in', 7200)
            EbayService._token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            EbayService._last_error = None
            return EbayService._access_token

        except requests.RequestException as e:
            EbayService._last_error = f"eBay auth error: {e}"
            EbayService._access_token = None
            EbayService._token_expires_at = None
            return None

    # Parole generiche TCG da rimuovere per eBay (troppo rumore)
    NOISE_WORDS = {
        'display', 'booster', 'box', 'bundle', 'etb', 'elite', 'trainer',
        'buste', 'busta', 'bustine', 'carte', 'cards', 'pack', 'packs',
        'collection', 'collezione', 'premium', 'ultra', 'tin', 'latta',
        'set', 'expansion', 'espansione', 'sealed', 'sigillato', 'sigillata',
        'nuovo', 'nuova', 'new', 'tcg', 'gcc', 'gioco', 'game',
    }

    @staticmethod
    def simplify_query(query):
        """Semplifica aggressivamente la query per eBay: tiene solo le keyword distintive"""
        q = query
        # Rimuovi indicatore lingua tra parentesi
        q = re.sub(r'\s*\((IT|EN|JP|DE|FR|ES|KO|ZH|JAP|ITA|ENG)\)\s*', ' ', q, flags=re.IGNORECASE)
        # Rimuovi "N Buste/Bustine/Booster/Pack/Carte" con numero
        q = re.sub(r'\b\d+\s*(buste|bustine|booster|pack|carte|cards|box)\b', '', q, flags=re.IGNORECASE)
        # Rimuovi numeri isolati (es. "36")
        q = re.sub(r'\b\d+\b', '', q)
        # Rimuovi simboli: & / + e trattini
        q = re.sub(r'[&/+\-]', ' ', q)
        # Rimuovi parole generiche TCG
        words = q.split()
        words = [w for w in words if w.lower() not in EbayService.NOISE_WORDS]
        # Tieni max 5 parole significative
        q = ' '.join(words[:5])
        q = re.sub(r'\s+', ' ', q).strip()
        return q

    def search(self, query, num_results=50):
        """Ricerca su eBay con multi-marketplace e query semplificata"""
        if not self.is_configured():
            return {'error': 'eBay not configured', 'results': []}

        token = self._get_access_token()
        if not token:
            token = self._get_access_token(force_refresh=True)
            if not token:
                return {'error': f'eBay authentication failed: {self.get_last_error()}', 'results': []}

        all_results = []
        seen_ids = set()  # Evita duplicati tra marketplace

        # Query originale + semplificata
        queries = [query]
        simplified = self.simplify_query(query)
        if simplified.lower() != query.lower():
            queries.append(simplified)

        # Cerca su marketplace primario, poi EU se servono più risultati
        marketplaces = [self.primary_marketplace]
        for mp in self.MARKETPLACES:
            if mp != self.primary_marketplace:
                marketplaces.append(mp)

        for marketplace in marketplaces:
            if len(all_results) >= num_results:
                break

            for q in queries:
                if len(all_results) >= num_results:
                    break

                results = self._search_marketplace(token, q, marketplace, num_results, seen_ids)
                all_results.extend(results)

                # Se il primo marketplace con query originale dà abbastanza risultati, basta
                if marketplace == self.primary_marketplace and len(all_results) >= 10:
                    break

        EbayService._last_error = None
        return {
            'results': all_results[:num_results],
            'total': len(all_results[:num_results]),
        }

    def _search_marketplace(self, token, query, marketplace, num_results, seen_ids):
        """Singola ricerca su un marketplace"""
        headers = {
            'Authorization': f'Bearer {token}',
            'X-EBAY-C-MARKETPLACE-ID': marketplace,
            'Content-Type': 'application/json',
        }

        params = {
            'q': query,
            'limit': min(num_results, 200),
            'filter': 'conditionIds:{1000|1500}',
        }

        try:
            response = requests.get(self.SEARCH_URL, headers=headers, params=params, timeout=30)

            if response.status_code == 401:
                token = self._get_access_token(force_refresh=True)
                if not token:
                    return []
                headers['Authorization'] = f'Bearer {token}'
                response = requests.get(self.SEARCH_URL, headers=headers, params=params, timeout=30)

            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get('itemSummaries', []):
                item_id = item.get('itemId', '')
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

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

            if results:
                print(f"[eBay] {marketplace} q=\"{query[:50]}\" -> {len(results)} results")
            return results

        except requests.RequestException as e:
            error_msg = str(e)
            if '401' in error_msg:
                error_msg = 'eBay: Token scaduto'
            elif '403' in error_msg:
                error_msg = 'eBay: Accesso negato'
            elif '429' in error_msg:
                error_msg = 'eBay: Troppe richieste'
            EbayService._last_error = error_msg
            return []

    def _extract_price(self, item):
        price_info = item.get('price', {})
        value = price_info.get('value')
        if value:
            try:
                return float(value)
            except ValueError:
                pass
        return None
