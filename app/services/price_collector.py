import re
from datetime import datetime
from app import db
from app.models import Monitor, PriceRecord
from app.services.serpapi import SerpAPIService
from app.services.ebay import EbayService

class PriceCollector:
    
    # Keywords che indicano prodotti NON desiderati (lotti, usati, falsi, lingue straniere)
    NEGATIVE_KEYWORDS = [
        'lot ', ' lot', 'lotto',  # Con spazi per evitare match parziali
        '2x', '3x', '4x', '5x', 'x2 ', 'x3 ', 'x4 ', 'x5 ',
        'empty', 'no cards', 'senza carte', 'vuoto',
        'opened', 'aperto', 'used', 'usato', 'usata',
        'fake', 'replica', 'proxy', 'custom', 'unofficial',
        'japanese', 'japan', 'jap ', 'giapponese', 'giapp',
        'korean', 'coreano', 'chinese', 'cinese',
        'repack', 'repacked', 'resealed',
        'busta singola', 'bustina singola', 'singola busta',
        'raw', 'psa', 'bgs', 'cgc',  # Carte gradate
    ]
    
    # Parole da ignorare nel matching (articoli, preposizioni, ecc.)
    IGNORE_WORDS = {
        'di', 'del', 'della', 'dei', 'degli', 'delle', 
        'e', 'o', 'a', 'da', 'in', 'con', 'su', 'per', 'tra', 'fra',
        'the', 'an', 'of', 'and', 'or', 'for', 'to',
        '-', '–', ':', '(', ')', '[', ']',
        'pokemon', 'pokémon', 'tcg', 'card', 'cards', 'carte',
        'yu', 'gi', 'oh', 'yugioh',
        'magic', 'mtg', 'gathering',
    }
    
    # Parole chiave che devono matchare se presenti nella query
    IMPORTANT_KEYWORDS = {
        'booster', 'box', 'display', 'bundle', 'etb', 'elite', 'trainer',
        'blister', 'pack', 'tin', 'collection', 'premium', 'ultra',
        '36', '24', '18', '12', '10', '6', '3',  # Numeri comuni per quantità
    }
    
    def __init__(self):
        self.serpapi = SerpAPIService()
        self.ebay = EbayService()
    
    def collect_for_monitor(self, monitor):
        if monitor.source == 'google_shopping':
            service = self.serpapi
        elif monitor.source == 'ebay':
            service = self.ebay
        else:
            return {'error': f'Unknown source: {monitor.source}', 'saved': 0}
        
        if not service.is_configured():
            return {'error': f'{monitor.source} not configured', 'saved': 0}
        
        result = service.search(monitor.search_query)
        
        if 'error' in result and result.get('results') == []:
            return {'error': result['error'], 'saved': 0}
        
        your_price = monitor.product.price if monitor.product else None
        saved_count = 0
        skipped_duplicates = 0
        valid_count = 0
        
        today = datetime.utcnow().date()
        
        for item in result.get('results', []):
            # Applica filtro con search_query per matching keywords
            is_valid = self._validate_result(item, your_price, monitor.price_tolerance, monitor.search_query)
            
            if is_valid:
                valid_count += 1
            
            seller_name = item.get('seller_name', '')[:255] if item.get('seller_name') else None
            
            # Evita duplicati: stesso monitor + stesso venditore + stesso giorno
            existing = PriceRecord.query.filter(
                PriceRecord.monitor_id == monitor.id,
                PriceRecord.seller_name == seller_name,
                db.func.date(PriceRecord.fetched_at) == today
            ).first()
            
            if existing:
                # Aggiorna il prezzo se è cambiato
                if existing.price != item['price']:
                    existing.price = item['price']
                    existing.is_valid = is_valid
                    existing.fetched_at = datetime.utcnow()
                skipped_duplicates += 1
                continue
            
            record = PriceRecord(
                monitor_id=monitor.id,
                title=item['title'][:500],
                price=item['price'],
                currency=item.get('currency', 'EUR'),
                seller_name=seller_name,
                seller_rating=item.get('seller_rating'),
                url=item.get('url', '')[:2000],
                source=item.get('source', monitor.source),
                is_valid=is_valid,
                fetched_at=datetime.utcnow(),
            )
            
            db.session.add(record)
            saved_count += 1
        
        monitor.last_run_at = datetime.utcnow()
        db.session.commit()
        
        return {
            'total_results': len(result.get('results', [])),
            'saved': saved_count,
            'valid': valid_count,
            'skipped_duplicates': skipped_duplicates,
        }
    
    def _validate_result(self, item, your_price, tolerance, search_query=None):
        title_lower = item.get('title', '').lower()
        
        # 1. Check negative keywords
        for keyword in self.NEGATIVE_KEYWORDS:
            if keyword in title_lower:
                return False
        
        # 2. Check that key search terms are present in title
        if search_query:
            if not self._match_keywords(search_query, title_lower):
                return False
        
        # 3. Check price range
        if your_price and your_price > 0:
            min_price = your_price * (1 - tolerance / 100)
            max_price = your_price * (1 + tolerance / 100)
            if not (min_price <= item['price'] <= max_price):
                return False
        
        return True
    
    def _match_keywords(self, search_query, title):
        """
        Verifica che le parole chiave importanti della query siano presenti nel titolo.
        Le IMPORTANT_KEYWORDS devono matchare se presenti nella query.
        """
        query_lower = search_query.lower()
        title_lower = title.lower()
        
        # Estrai tutte le parole dalla query
        query_words = re.findall(r'\w+', query_lower)
        
        # 1. Verifica le parole importanti (DEVONO matchare se nella query)
        for word in query_words:
            if word in self.IMPORTANT_KEYWORDS:
                if word not in title_lower:
                    # Eccezione: "box" può essere "booster box" -> ok se c'è "booster"
                    if word == 'box' and 'booster' in query_lower and 'booster' in title_lower:
                        continue
                    return False
        
        # 2. Verifica che non ci siano keyword importanti nel titolo che NON sono nella query
        # Es: query="Booster Box" ma titolo="Gift Bundle" -> INVALID perché "bundle" è importante ma non nella query
        for word in self.IMPORTANT_KEYWORDS:
            if word in title_lower and word not in query_lower:
                # Il titolo ha una keyword importante che non è nella query
                # Questo potrebbe essere un prodotto diverso
                if word in ['bundle', 'etb', 'elite', 'trainer', 'tin', 'blister', 'collection', 'premium']:
                    return False
        
        # 3. Verifica parole significative (almeno 50% match)
        significant_words = [w for w in query_words if w not in self.IGNORE_WORDS and len(w) > 2]
        
        if not significant_words:
            return True
        
        matches = sum(1 for word in significant_words if word in title_lower)
        required_matches = max(1, int(len(significant_words) * 0.5))
        
        return matches >= required_matches
    
    def _filter_results(self, results, search_query, your_price=None, tolerance=50):
        """
        Filtra i risultati applicando tutti i criteri di validazione.
        Ritorna solo i risultati validi.
        """
        valid_results = []
        for item in results:
            if self._validate_result(item, your_price, tolerance, search_query):
                item['is_valid'] = True
                valid_results.append(item)
            else:
                item['is_valid'] = False
        return valid_results
    
    def test_search(self, source, query, filter_results=True):
        if source == 'google_shopping':
            service = self.serpapi
        elif source == 'ebay':
            service = self.ebay
        else:
            return {'error': f'Unknown source: {source}', 'results': []}
        
        if not service.is_configured():
            return {'error': f'{source} not configured', 'results': []}
        
        result = service.search(query, num_results=20)
        
        if filter_results and 'results' in result:
            all_results = result['results']
            valid_results = self._filter_results(all_results, query)
            result['results'] = valid_results
            result['filtered_out'] = len(all_results) - len(valid_results)
            result['total_raw'] = len(all_results)
        
        return result
