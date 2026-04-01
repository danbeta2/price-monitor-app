import re
from datetime import datetime
from app import db
from app.models import Monitor, PriceRecord
from app.services.serpapi import SerpAPIService
from app.services.ebay import EbayService

class PriceCollector:
    
    NEGATIVE_KEYWORDS = [
        'lot', 'lotto', '2x', '3x', '4x', '5x', 'x2', 'x3', 'x4', 'x5',
        'bundle', 'empty', 'no cards', 'senza carte',
        'opened', 'used', 'usato', 'fake', 'replica', 'proxy', 'custom',
        'japanese', 'jap', 'giapponese', 'korean', 'coreano', 'chinese', 'cinese', 
        'repack', 'display', 'box', 'case', 'master', 'booster box',
        'busta', 'bustina', 'bustine', 'buste', 'singola', 'singolo',
        'coppia', 'doppio', 'doppia', 'triple', 'triplo'
    ]
    
    # Parole da ignorare nel matching (articoli, preposizioni, ecc.)
    IGNORE_WORDS = {'di', 'del', 'della', 'dei', 'degli', 'delle', 'e', 'o', 'a', 'da', 'in', 'con', 'su', 'per', 'tra', 'fra', 'the', 'a', 'an', 'of', 'and', 'or', '-', '–', ':', '(', ')', '[', ']'}
    
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
        
        for item in result.get('results', []):
            is_valid = self._validate_result(item, your_price, monitor.price_tolerance)
            
            record = PriceRecord(
                monitor_id=monitor.id,
                title=item['title'][:500],
                price=item['price'],
                currency=item.get('currency', 'EUR'),
                seller_name=item.get('seller_name', '')[:255] if item.get('seller_name') else None,
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
            'valid': sum(1 for r in result.get('results', []) if self._validate_result(r, your_price, monitor.price_tolerance)),
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
        Richiede che almeno l'80% delle parole significative siano presenti.
        """
        # Normalizza e splitta la query
        query_words = re.findall(r'\w+', search_query.lower())
        
        # Rimuovi parole da ignorare
        significant_words = [w for w in query_words if w not in self.IGNORE_WORDS and len(w) > 2]
        
        if not significant_words:
            return True
        
        # Conta quante parole significative sono nel titolo
        matches = sum(1 for word in significant_words if word in title)
        
        # Richiedi almeno 80% di match (minimo 2 parole se ne abbiamo abbastanza)
        required_matches = max(2, int(len(significant_words) * 0.8))
        
        return matches >= min(required_matches, len(significant_words))
    
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
