import re
from datetime import datetime
from app import db
from app.models import Monitor, PriceRecord
from app.services.serpapi import SerpAPIService
from app.services.ebay import EbayService

class PriceCollector:
    
    # Keywords che indicano prodotti NON desiderati
    NEGATIVE_KEYWORDS = [
        # Lotti e multipli
        'lot ', ' lot', 'lotto', 'lotti',
        '2x', '3x', '4x', '5x', '6x', '10x',
        'x2 ', 'x3 ', 'x4 ', 'x5 ', 'x6 ', 'x10',
        
        # Usato/aperto/danneggiato
        'empty', 'vuoto', 'vuota', 'no cards', 'senza carte',
        'opened', 'aperto', 'aperta', 'used', 'usato', 'usata',
        'damaged', 'danneggiato', 'danneggiata',
        
        # Falsi/custom
        'fake', 'replica', 'proxy', 'custom', 'unofficial', 'fan made',
        
        # Repacked
        'repack', 'repacked', 'resealed', 'riconfezionato',
        
        # Carte singole / gradate
        'singola', 'singolo', 'single',
        'raw', 'psa ', 'bgs ', 'cgc ', 'graded', 'gradato',
        
        # Accessori
        'sleeves', 'bustine protettive', 'deck box', 'playmat', 'tappetino',
    ]
    
    # Keywords per lingua straniera (da escludere se lingua='it' o 'en')
    FOREIGN_LANGUAGE_KEYWORDS = {
        'ja': ['japanese', 'japan', 'jap ', 'giapponese', 'giapp', '日本語', 'jp'],
        'ko': ['korean', 'coreano', 'corea', '한국어', 'kr'],
        'zh': ['chinese', 'cinese', 'cina', '中文', 'cn', 'taiwan'],
        'de': ['german', 'tedesco', 'deutsch'],
        'fr': ['french', 'francese', 'français'],
        'es': ['spanish', 'spagnolo', 'español'],
        'pt': ['portuguese', 'portoghese', 'português'],
    }
    
    # Parole da ignorare nel matching
    IGNORE_WORDS = {
        'di', 'del', 'della', 'dei', 'degli', 'delle', 
        'e', 'o', 'a', 'da', 'in', 'con', 'su', 'per', 'tra', 'fra',
        'the', 'an', 'of', 'and', 'or', 'for', 'to', 'with',
        '-', '–', ':', '(', ')', '[', ']', '|',
        'pokemon', 'pokémon', 'tcg', 'card', 'cards', 'carte',
        'yu', 'gi', 'oh', 'yugioh',
        'magic', 'mtg', 'gathering',
        'sealed', 'sigillato', 'sigillata', 'new', 'nuovo', 'nuova',
    }
    
    # Keywords importanti che DEVONO matchare se presenti
    PRODUCT_TYPE_KEYWORDS = {
        'booster', 'box', 'display', 'bundle', 'etb', 'elite', 'trainer',
        'blister', 'pack', 'tin', 'collection', 'premium', 'ultra',
        'starter', 'deck', 'theme', 'structure',
        '36', '24', '18', '12', '10', '6', '3',
    }
    
    def __init__(self):
        self.serpapi = SerpAPIService()
        self.ebay = EbayService()
    
    def collect_for_monitor(self, monitor):
        """Raccoglie prezzi da tutte le fonti configurate per un monitor"""
        results = {
            'total_results': 0,
            'saved': 0,
            'valid': 0,
            'skipped_duplicates': 0,
            'sources': {}
        }
        
        your_price = monitor.product.price if monitor.product else None
        language = getattr(monitor, 'language', 'it') or 'it'
        source = getattr(monitor, 'source', 'all') or 'all'
        
        # Determina quali fonti usare
        sources_to_use = []
        if source == 'all':
            sources_to_use = ['google_shopping', 'google_web', 'ebay']
        elif source == 'both':  # Legacy: google_shopping + ebay
            sources_to_use = ['google_shopping', 'ebay']
        elif source == 'google':  # Entrambi i Google
            sources_to_use = ['google_shopping', 'google_web']
        else:
            sources_to_use = [source]
        
        all_items = []
        
        # Raccogli da ogni fonte
        for src in sources_to_use:
            if src == 'google_shopping' and self.serpapi.is_configured():
                result = self.serpapi.search(monitor.search_query, num_results=50)
                for item in result.get('results', []):
                    item['source'] = 'google_shopping'
                    all_items.append(item)
                results['sources']['google_shopping'] = len(result.get('results', []))
            
            elif src == 'google_web' and self.serpapi.is_configured():
                result = self.serpapi.search_web(monitor.search_query, num_results=30)
                for item in result.get('results', []):
                    item['source'] = 'google_web'
                    all_items.append(item)
                results['sources']['google_web'] = len(result.get('results', []))
                
            elif src == 'ebay' and self.ebay.is_configured():
                result = self.ebay.search(monitor.search_query, num_results=50)
                for item in result.get('results', []):
                    item['source'] = 'ebay'
                    all_items.append(item)
                results['sources']['ebay'] = len(result.get('results', []))
        
        if not all_items:
            return {'error': 'Nessuna fonte configurata o nessun risultato', **results}
        
        results['total_results'] = len(all_items)
        today = datetime.utcnow().date()
        
        # Processa e salva i risultati
        for item in all_items:
            is_valid = self._validate_result(
                item, 
                your_price, 
                monitor.price_tolerance, 
                monitor.search_query,
                language
            )
            
            if is_valid:
                results['valid'] += 1
            
            seller_name = item.get('seller_name', '')[:255] if item.get('seller_name') else None
            item_source = item.get('source', 'unknown')
            
            # Evita duplicati: stesso monitor + stesso venditore + stessa fonte + stesso giorno
            existing = PriceRecord.query.filter(
                PriceRecord.monitor_id == monitor.id,
                PriceRecord.seller_name == seller_name,
                PriceRecord.source == item_source,
                db.func.date(PriceRecord.fetched_at) == today
            ).first()
            
            if existing:
                if existing.price != item['price']:
                    existing.price = item['price']
                    existing.is_valid = is_valid
                    existing.fetched_at = datetime.utcnow()
                results['skipped_duplicates'] += 1
                continue
            
            record = PriceRecord(
                monitor_id=monitor.id,
                title=item['title'][:500],
                price=item['price'],
                currency=item.get('currency', 'EUR'),
                seller_name=seller_name,
                seller_rating=item.get('seller_rating'),
                url=item.get('url', '')[:2000],
                source=item_source,
                is_valid=is_valid,
                fetched_at=datetime.utcnow(),
            )
            
            db.session.add(record)
            results['saved'] += 1
        
        monitor.last_run_at = datetime.utcnow()
        db.session.commit()
        
        return results
    
    def _validate_result(self, item, your_price, tolerance, search_query, language='it'):
        """Valida un risultato - filtri più permissivi"""
        title = item.get('title', '')
        title_lower = title.lower()
        
        # 1. Check negative keywords (solo quelli critici)
        critical_negatives = [
            'lot ', ' lot', 'lotto', 'lotti', 'bundle of', 
            'empty', 'vuoto', 'vuota', 'no cards', 'senza carte',
            'fake', 'replica', 'proxy', 'custom', 'unofficial',
            'repack', 'repacked', 'resealed',
            'psa ', 'bgs ', 'cgc ', 'graded', 'gradato',
        ]
        for keyword in critical_negatives:
            if keyword.lower() in title_lower:
                return False
        
        # 2. Check lingua straniera (solo se è esplicitamente un'altra lingua)
        if language == 'it':
            foreign_explicit = ['japanese', 'giapponese', 'korean', 'coreano', 'chinese', 'cinese']
            for kw in foreign_explicit:
                if kw in title_lower:
                    return False
        
        # 3. Verifica keywords principali (più permissivo)
        if not self._match_main_keywords(search_query, title_lower):
            return False
        
        # 4. Check price range (range più ampio: tolleranza x2)
        if your_price and your_price > 0:
            effective_tolerance = min(tolerance * 2, 100)  # Max 100%
            min_price = your_price * (1 - effective_tolerance / 100)
            max_price = your_price * (1 + effective_tolerance / 100)
            price = item.get('price', 0)
            if not (min_price * 0.5 <= price <= max_price * 1.5):  # Ancora più permissivo
                return False
        
        return True
    
    def _match_product_type(self, search_query, title):
        """Verifica che il tipo di prodotto corrisponda"""
        query_lower = search_query.lower()
        
        # Trova quali tipi di prodotto sono nella query
        query_types = []
        for keyword in self.PRODUCT_TYPE_KEYWORDS:
            if keyword in query_lower:
                query_types.append(keyword)
        
        if not query_types:
            return True
        
        # Verifica che almeno uno dei tipi sia nel titolo
        for pt in query_types:
            if pt in title:
                continue
            # Se la query ha "box" ma il titolo ha "bundle" -> INVALID
            if pt in ['box', 'display'] and ('bundle' in title or 'tin' in title or 'blister' in title):
                return False
            if pt == 'bundle' and ('box' in title and 'display' in title):
                return False
            if pt == 'etb' and 'etb' not in title and 'elite trainer' not in title:
                return False
        
        # Verifica che il titolo non abbia tipi diversi non richiesti
        title_types = [k for k in self.PRODUCT_TYPE_KEYWORDS if k in title]
        for tt in title_types:
            if tt not in query_types:
                # Il titolo ha un tipo non richiesto
                if tt in ['bundle', 'etb', 'tin', 'blister', 'starter', 'deck', 'theme', 'structure']:
                    # Questi sono tipi specifici, se non richiesti -> invalid
                    if tt not in query_lower:
                        return False
        
        return True
    
    def _match_main_keywords(self, search_query, title):
        """Verifica che le parole chiave principali siano presenti - più permissivo"""
        query_words = re.findall(r'\w+', search_query.lower())
        
        # Filtra parole da ignorare
        significant_words = [
            w for w in query_words 
            if w not in self.IGNORE_WORDS 
            and w not in self.PRODUCT_TYPE_KEYWORDS
            and len(w) > 2
        ]
        
        if not significant_words:
            return True
        
        # Per carte singole (contengono numeri tipo 001/191), basta match parziale
        has_card_number = any(c.isdigit() for c in search_query)
        
        # Conta match
        matches = sum(1 for word in significant_words if word in title)
        
        # Per carte: basta 1 match. Per prodotti sealed: 40% match
        if has_card_number:
            required = 1
        else:
            required = max(1, int(len(significant_words) * 0.4))
        
        return matches >= required
    
    def _filter_results(self, results, search_query, your_price=None, tolerance=50, language='it'):
        """Filtra una lista di risultati"""
        valid_results = []
        for item in results:
            is_valid = self._validate_result(item, your_price, tolerance, search_query, language)
            item['is_valid'] = is_valid
            if is_valid:
                valid_results.append(item)
        return valid_results
    
    def test_search(self, source, query, filter_results=True, language='it'):
        """Test di ricerca su una o più fonti"""
        all_results = []
        total_raw = 0
        errors = {}
        
        # Mappa source a lista di fonti
        if source == 'all':
            sources = ['google_shopping', 'google_web', 'ebay']
        elif source == 'both':  # Legacy
            sources = ['google_shopping', 'ebay']
        elif source == 'google':
            sources = ['google_shopping', 'google_web']
        else:
            sources = [source]
        
        for src in sources:
            if src == 'google_shopping':
                if not self.serpapi.is_configured():
                    errors['google_shopping'] = 'Non configurato'
                    continue
                result = self.serpapi.search(query, num_results=30)
                for item in result.get('results', []):
                    item['source'] = 'google_shopping'
                    all_results.append(item)
                total_raw += len(result.get('results', []))
                if result.get('error'):
                    errors['google_shopping'] = result['error']
            
            elif src == 'google_web':
                if not self.serpapi.is_configured():
                    errors['google_web'] = 'Non configurato'
                    continue
                result = self.serpapi.search_web(query, num_results=20)
                for item in result.get('results', []):
                    item['source'] = 'google_web'
                    all_results.append(item)
                total_raw += len(result.get('results', []))
                if result.get('error'):
                    errors['google_web'] = result['error']
                    
            elif src == 'ebay':
                if not self.ebay.is_configured():
                    errors['ebay'] = 'Non configurato'
                    continue
                result = self.ebay.search(query, num_results=30)
                for item in result.get('results', []):
                    item['source'] = 'ebay'
                    all_results.append(item)
                total_raw += len(result.get('results', []))
                if result.get('error'):
                    errors['ebay'] = result['error']
        
        if filter_results:
            valid_results = self._filter_results(all_results, query, language=language)
            valid_results.sort(key=lambda x: x.get('price', 999999))
            return {
                'results': valid_results,
                'total': len(valid_results),
                'total_raw': total_raw,
                'filtered_out': total_raw - len(valid_results),
                'google_shopping_count': len([r for r in valid_results if r.get('source') == 'google_shopping']),
                'google_web_count': len([r for r in valid_results if r.get('source') == 'google_web']),
                'ebay_count': len([r for r in valid_results if r.get('source') == 'ebay']),
                'errors': errors if errors else None,
            }
        
        all_results.sort(key=lambda x: x.get('price', 999999))
        return {
            'results': all_results,
            'total': len(all_results),
            'total_raw': total_raw,
            'errors': errors if errors else None,
        }
