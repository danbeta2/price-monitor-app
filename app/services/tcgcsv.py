"""
TCGCSV Service - Free TCGPlayer price data via tcgcsv.com
Provides sealed product prices (USD) with daily updates.
"""
import requests
import re
from datetime import datetime, timedelta

class TCGCSVService:
    BASE_URL = "https://tcgcsv.com/tcgplayer"

    # TCGPlayer category IDs
    CATEGORIES = {
        'pokemon': 3,
        'magic': 1,
        'yugioh': 2,
        'one_piece': 87,
        'lorcana': 89,
        'dragon_ball': 64,
    }

    # Cache per groups e products (aggiornato 1x/giorno)
    _groups_cache = {}       # {category_id: {data, fetched_at}}
    _products_cache = {}     # {(category_id, group_id): {data, fetched_at}}
    _prices_cache = {}       # {(category_id, group_id): {data, fetched_at}}
    CACHE_TTL = timedelta(hours=6)

    def _cached_get(self, cache, key, url):
        """GET con cache in memoria"""
        if key in cache:
            entry = cache[key]
            if datetime.utcnow() - entry['fetched_at'] < self.CACHE_TTL:
                return entry['data']

        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            cache[key] = {'data': data, 'fetched_at': datetime.utcnow()}
            return data
        except Exception as e:
            print(f"[TCGCSV] Error fetching {url}: {e}")
            return None

    def get_groups(self, category_id):
        """Lista set/espansioni per una categoria"""
        url = f"{self.BASE_URL}/{category_id}/groups"
        data = self._cached_get(self._groups_cache, category_id, url)
        if not data:
            return []
        return data.get('results', [])

    def get_products(self, category_id, group_id):
        """Lista prodotti per un set"""
        key = (category_id, group_id)
        url = f"{self.BASE_URL}/{category_id}/{group_id}/products"
        data = self._cached_get(self._products_cache, key, url)
        if not data:
            return []
        return data.get('results', [])

    def get_prices(self, category_id, group_id):
        """Prezzi per un set"""
        key = (category_id, group_id)
        url = f"{self.BASE_URL}/{category_id}/{group_id}/prices"
        data = self._cached_get(self._prices_cache, key, url)
        if not data:
            return []
        return data.get('results', [])

    def get_sealed_products_with_prices(self, category_id, group_id):
        """Ritorna solo i prodotti sealed con prezzi (filtro client-side)"""
        products = self.get_products(category_id, group_id)
        prices = self.get_prices(category_id, group_id)

        if not products or not prices:
            return []

        # Mappa prezzi per productId (solo subTypeName=Normal per sealed)
        price_map = {}
        for p in prices:
            if p.get('subTypeName') == 'Normal':
                price_map[p['productId']] = p

        # Filtra sealed: prodotti SENZA "Number" in extendedData
        sealed = []
        for prod in products:
            ext_data = prod.get('extendedData', [])
            has_number = any(e.get('name') == 'Number' for e in ext_data)
            if has_number:
                continue  # E' una carta singola

            price_info = price_map.get(prod['productId'])
            if not price_info or not price_info.get('marketPrice'):
                continue

            sealed.append({
                'productId': prod['productId'],
                'name': prod.get('cleanName') or prod.get('name', ''),
                'imageUrl': prod.get('imageUrl', ''),
                'url': prod.get('url', ''),
                'marketPrice': price_info.get('marketPrice'),
                'lowPrice': price_info.get('lowPrice'),
                'midPrice': price_info.get('midPrice'),
                'highPrice': price_info.get('highPrice'),
            })

        return sealed

    def detect_category(self, product_name):
        """Rileva la categoria TCG dal nome prodotto"""
        name_lower = product_name.lower()
        if any(w in name_lower for w in ['pokemon', 'pokémon', 'pikachu', 'charizard']):
            return self.CATEGORIES['pokemon']
        if any(w in name_lower for w in ['magic', 'mtg', 'gathering']):
            return self.CATEGORIES['magic']
        if any(w in name_lower for w in ['yugioh', 'yu-gi-oh', 'konami']):
            return self.CATEGORIES['yugioh']
        if any(w in name_lower for w in ['one piece']):
            return self.CATEGORIES.get('one_piece')
        if any(w in name_lower for w in ['lorcana', 'disney']):
            return self.CATEGORIES.get('lorcana')
        if any(w in name_lower for w in ['dragon ball']):
            return self.CATEGORIES.get('dragon_ball')
        return self.CATEGORIES['pokemon']  # Default

    def search_sealed(self, product_name, max_results=10):
        """Cerca prodotti sealed per nome su TCGCSV.
        Ritorna i migliori match con prezzi TCGPlayer (USD)."""
        category_id = self.detect_category(product_name)
        if not category_id:
            return {'error': 'Categoria non supportata', 'results': []}

        # Pulisci il nome per il matching
        clean_name = self._clean_for_search(product_name)
        search_words = set(clean_name.lower().split())

        # Cerca il gruppo (set) migliore
        groups = self.get_groups(category_id)
        if not groups:
            return {'error': 'Impossibile caricare i set', 'results': []}

        # Prima prova a trovare il set dal nome
        best_group = self._find_best_group(groups, product_name)

        if best_group:
            # Cerca nel set specifico
            sealed = self.get_sealed_products_with_prices(category_id, best_group['groupId'])
            matches = self._rank_matches(sealed, search_words, max_results)
            if matches:
                return {
                    'results': matches,
                    'group': best_group.get('name', ''),
                    'category_id': category_id,
                    'source': 'tcgplayer_via_tcgcsv',
                    'currency': 'USD',
                }

        # Fallback: cerca nei set più recenti
        recent_groups = sorted(groups, key=lambda g: g.get('publishedOn', ''), reverse=True)[:10]
        all_matches = []
        for group in recent_groups:
            sealed = self.get_sealed_products_with_prices(category_id, group['groupId'])
            matches = self._rank_matches(sealed, search_words, 3)
            for m in matches:
                m['group_name'] = group.get('name', '')
            all_matches.extend(matches)

        all_matches.sort(key=lambda x: x.get('score', 0), reverse=True)

        return {
            'results': all_matches[:max_results],
            'group': 'Multiple sets',
            'category_id': category_id,
            'source': 'tcgplayer_via_tcgcsv',
            'currency': 'USD',
        }

    def _clean_for_search(self, name):
        """Pulisce il nome per la ricerca"""
        # Rimuovi lingua, numeri buste, trattini, simboli
        n = re.sub(r'\s*\((IT|EN|JP|DE|FR|ES|KO|ZH)\)\s*', ' ', name, flags=re.IGNORECASE)
        n = re.sub(r'\b\d+\s*(buste|bustine|booster|pack|carte)\b', '', n, flags=re.IGNORECASE)
        n = re.sub(r'[&/+\-:,]', ' ', n)
        n = re.sub(r'\b\d+\b', '', n)
        n = re.sub(r'\s+', ' ', n).strip()
        return n

    # Mapping nomi italiani -> inglesi per espansioni note
    IT_TO_EN = {
        'scintille folgoranti': 'sparking zero',  # SV08.5
        'scarlatto': 'scarlet', 'violetto': 'violet',
        'fiamme ossidiana': 'obsidian flames',
        'evoluzioni a paldea': 'paldea evolved',
        'forze temporali': 'temporal forces',
        'destino di paldea': 'paldean fates',
        'corona astrale': 'stellar crown',
        'scarlatto e violetto': 'scarlet violet',
        'scontro paradosso': 'paradox rift',
        'futuri ancestrali': 'ancient origins',
        'nebbie prismatiche': 'prismatic evolutions',
        'supercarica energetica': 'surging sparks',
        'crepuscolo mascherato': 'twilight masquerade',
        'destini brillanti': 'shining fates',
        'voltaggio vivido': 'vivid voltage',
        'regno glaciale': 'chilling reign',
        'celebrazioni': 'celebrations',
        'stelle lucenti': 'brilliant stars',
        'tempesta argentata': 'silver tempest',
        'spada e scudo': 'sword shield',
        'sole e luna': 'sun moon',
    }

    def _translate_to_en(self, name):
        """Traduce nomi espansione IT -> EN per matching TCGCSV"""
        result = name.lower()
        for it_name, en_name in self.IT_TO_EN.items():
            result = result.replace(it_name, en_name)
        return result

    def _find_best_group(self, groups, product_name):
        """Trova il set migliore per un prodotto"""
        clean = self._clean_for_search(product_name).lower()
        translated = self._translate_to_en(clean)
        search_words = set(translated.split())

        # Rimuovi parole generiche
        generic = {'display', 'booster', 'box', 'bundle', 'etb', 'elite', 'trainer',
                    'collection', 'premium', 'ultra', 'tin', 'pokemon', 'pokémon',
                    'magic', 'yugioh', 'the', 'of', 'and', 'a', 'in', 'da'}
        search_words -= generic

        if not search_words:
            return None

        best_score = 0
        best_group = None

        for group in groups:
            group_name = group.get('name', '').lower()
            group_words = set(re.findall(r'\w+', group_name))

            # Quante parole di ricerca matchano nel nome del gruppo
            matches = search_words & group_words
            if matches:
                score = len(matches) / len(search_words)
                if score > best_score:
                    best_score = score
                    best_group = group

        return best_group if best_score >= 0.3 else None

    def _rank_matches(self, sealed_products, search_words, max_results):
        """Classifica i sealed products per rilevanza"""
        scored = []
        for prod in sealed_products:
            name_words = set(prod['name'].lower().split())
            matches = search_words & name_words
            score = len(matches) / max(len(search_words), 1)
            if score > 0 or len(search_words) == 0:
                scored.append({**prod, 'score': score})

        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored[:max_results]
