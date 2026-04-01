from datetime import datetime
from app import db
from app.models import Monitor, PriceRecord
from app.services.serpapi import SerpAPIService
from app.services.ebay import EbayService

class PriceCollector:
    
    NEGATIVE_KEYWORDS = [
        'lot', '2x', '3x', '4x', '5x', 'bundle', 'empty', 'no cards',
        'opened', 'used', 'fake', 'replica', 'proxy', 'custom',
        'japanese', 'jap', 'korean', 'chinese', 'repack'
    ]
    
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
    
    def _validate_result(self, item, your_price, tolerance):
        title_lower = item.get('title', '').lower()
        for keyword in self.NEGATIVE_KEYWORDS:
            if keyword in title_lower:
                return False
        
        if your_price and your_price > 0:
            min_price = your_price * (1 - tolerance / 100)
            max_price = your_price * (1 + tolerance / 100)
            if not (min_price <= item['price'] <= max_price):
                return False
        
        return True
    
    def test_search(self, source, query):
        if source == 'google_shopping':
            service = self.serpapi
        elif source == 'ebay':
            service = self.ebay
        else:
            return {'error': f'Unknown source: {source}', 'results': []}
        
        if not service.is_configured():
            return {'error': f'{source} not configured', 'results': []}
        
        return service.search(query, num_results=10)
