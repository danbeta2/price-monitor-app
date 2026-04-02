from flask import Blueprint, jsonify, request
from app import db
from app.models import Product, Monitor, PriceRecord
from app.services.woocommerce import WooCommerceService
from app.services.price_collector import PriceCollector
from sqlalchemy import func
from datetime import datetime, timedelta
import re

api_bp = Blueprint('api', __name__)

def is_single_card(name):
    """Verifica se un prodotto è una carta singola (pattern: 001/191, 204/182, etc.)"""
    if not name:
        return False
    # Pattern: numero/numero all'inizio del nome (es. "001/191 Exeggcute...")
    single_card_pattern = r'^\d{1,3}/\d{1,3}\s'
    return bool(re.match(single_card_pattern, name))

@api_bp.route('/products')
def get_products():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    category = request.args.get('category', type=int)
    search = request.args.get('search', '')
    in_stock_only = request.args.get('in_stock_only', 'false').lower() == 'true'
    
    wc = WooCommerceService()
    all_products = wc.get_products(page=page, per_page=per_page, category=category, search=search, in_stock_only=in_stock_only)
    
    # Filtra carte singole - NON devono comparire mai
    products = [p for p in all_products if not is_single_card(p.get('name', ''))]
    
    return jsonify({
        'products': products,
        'page': page,
        'per_page': per_page,
    })

@api_bp.route('/categories')
def get_categories():
    wc = WooCommerceService()
    categories = wc.get_categories()
    return jsonify({'categories': categories})

@api_bp.route('/debug/config')
def debug_config():
    """Endpoint di debug per verificare le configurazioni"""
    from flask import current_app
    return jsonify({
        'wc_url': bool(current_app.config.get('WC_URL')),
        'wc_url_value': (current_app.config.get('WC_URL', '')[:30] + '...') if current_app.config.get('WC_URL') else None,
        'wc_key': bool(current_app.config.get('WC_CONSUMER_KEY')),
        'wc_key_prefix': current_app.config.get('WC_CONSUMER_KEY', '')[:10] + '...' if current_app.config.get('WC_CONSUMER_KEY') else None,
        'wc_secret': bool(current_app.config.get('WC_CONSUMER_SECRET')),
        'serpapi': bool(current_app.config.get('SERPAPI_KEY')),
        'ebay_id': bool(current_app.config.get('EBAY_CLIENT_ID')),
        'ebay_secret': bool(current_app.config.get('EBAY_CLIENT_SECRET')),
    })

@api_bp.route('/api-status')
def api_status():
    """Ritorna lo stato delle API e crediti rimanenti"""
    from app.services.serpapi import SerpAPIService
    from app.services.ebay import EbayService
    
    serpapi = SerpAPIService()
    ebay = EbayService()
    
    result = {
        'serpapi': {
            'configured': serpapi.is_configured(),
            'remaining_searches': None,
            'warning': None,
        },
        'ebay': {
            'configured': ebay.is_configured(),
            'last_error': ebay.get_last_error(),
        }
    }
    
    if serpapi.is_configured():
        result['serpapi']['remaining_searches'] = serpapi.get_remaining_searches()
        warning = serpapi.get_usage_warning()
        if warning:
            result['serpapi']['warning'] = warning
    
    return jsonify(result)

@api_bp.route('/sync-products', methods=['POST'])
def sync_products():
    wc = WooCommerceService()
    
    if not wc.is_configured():
        from flask import current_app
        return jsonify({
            'error': 'WooCommerce non configurato',
            'details': f"WC_URL: {'✓' if current_app.config.get('WC_URL') else '✗'}, KEY: {'✓' if current_app.config.get('WC_CONSUMER_KEY') else '✗'}, SECRET: {'✓' if current_app.config.get('WC_CONSUMER_SECRET') else '✗'}",
            'synced': 0
        }), 400
    
    synced = 0
    skipped_single_cards = 0
    
    print("[Sync] Starting sync (SOLO prodotti SEALED disponibili, no carte singole)...")
    
    try:
        page = 1
        max_pages = 10  # Limite sicurezza: max 500 prodotti
        
        while page <= max_pages:
            print(f"[Sync] Fetching page {page} (in_stock_only=True)...")
            batch = wc.get_products(page=page, per_page=50, in_stock_only=True)
            
            if batch is None and page == 1:
                return jsonify({
                    'error': 'Errore connessione WooCommerce',
                    'details': wc.last_error or 'Impossibile connettersi',
                    'synced': 0
                }), 500
            
            if not batch:
                break
            
            # Processa questo batch e commit subito
            for wc_product in batch:
                product_name = wc_product.get('name', '')
                
                # ESCLUDI carte singole fin dalla sincronizzazione
                if is_single_card(product_name):
                    skipped_single_cards += 1
                    continue
                
                product = Product.query.filter_by(wc_product_id=wc_product['id']).first()
                
                if not product:
                    product = Product(wc_product_id=wc_product['id'])
                    db.session.add(product)
                
                product.name = wc_product.get('name', '')[:500]
                product.sku = wc_product.get('sku', '')[:100] if wc_product.get('sku') else None
                product.price = float(wc_product.get('price') or 0)
                product.stock_status = 'instock'  # Sempre instock perché filtriamo
                product.stock_quantity = wc_product.get('stock_quantity') or 0
                
                images = wc_product.get('images', [])
                if images:
                    product.image_url = images[0].get('src', '')[:1000]
                
                synced += 1
            
            # Commit dopo ogni batch per evitare timeout
            db.session.commit()
            print(f"[Sync] Page {page} done, total synced: {synced}")
            
            if len(batch) < 50:
                break
            
            page += 1
        
        print(f"[Sync] Completed: {synced} prodotti sealed sincronizzati, {skipped_single_cards} carte singole ignorate")
        
        # Rimuovi prodotti esauriti o carte singole dal database (senza monitor attivi)
        removed = 0
        all_products = Product.query.all()
        for p in all_products:
            # Rimuovi se: esaurito OPPURE carta singola (senza monitor attivi)
            should_remove = p.stock_status != 'instock' or is_single_card(p.name)
            if should_remove:
                active_monitors = Monitor.query.filter_by(product_id=p.id, is_active=True).count()
                if active_monitors == 0:
                    db.session.delete(p)
                    removed += 1
        
        if removed > 0:
            db.session.commit()
            print(f"[Sync] Removed {removed} products (out-of-stock or single cards)")
        
        return jsonify({
            'synced': synced,
            'skipped_single_cards': skipped_single_cards,
            'removed': removed,
            'message': f'Sincronizzati {synced} prodotti sealed' + (f', ignorate {skipped_single_cards} carte singole' if skipped_single_cards > 0 else '') + (f', rimossi {removed}' if removed > 0 else '')
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"[Sync] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': 'Errore durante la sincronizzazione',
            'details': str(e),
            'synced': synced
        }), 500

@api_bp.route('/monitors', methods=['GET'])
def get_monitors():
    monitors = Monitor.query.all()
    result = []
    
    for m in monitors:
        data = m.to_dict()
        data['product'] = m.product.to_dict() if m.product else None
        
        # Prima cerca tra i validi
        best_price = PriceRecord.query.filter_by(
            monitor_id=m.id, is_valid=True
        ).order_by(PriceRecord.price.asc()).first()
        
        # Se non ci sono validi, prendi comunque il miglior prezzo (per riferimento)
        if not best_price:
            best_price = PriceRecord.query.filter_by(
                monitor_id=m.id
            ).order_by(PriceRecord.price.asc()).first()
            data['best_price_unvalidated'] = True
        else:
            data['best_price_unvalidated'] = False
        
        data['best_price'] = best_price.price if best_price else None
        data['best_seller'] = best_price.seller_name if best_price else None
        
        # Conta record totali e validi
        data['total_records'] = PriceRecord.query.filter_by(monitor_id=m.id).count()
        data['valid_records'] = PriceRecord.query.filter_by(monitor_id=m.id, is_valid=True).count()
        
        result.append(data)
    
    return jsonify({'monitors': result})

@api_bp.route('/monitors', methods=['POST'])
def create_monitor():
    data = request.json
    
    product_id = data.get('product_id')
    wc_product_id = data.get('wc_product_id')
    search_query = data.get('search_query', '')
    source = data.get('source', 'google_shopping')
    
    if wc_product_id:
        product = Product.query.filter_by(wc_product_id=wc_product_id).first()
        if not product:
            wc = WooCommerceService()
            wc_product = wc.get_product(wc_product_id)
            if not wc_product:
                return jsonify({'error': 'Product not found'}), 404
            
            product = Product(
                wc_product_id=wc_product_id,
                name=wc_product.get('name', ''),
                sku=wc_product.get('sku'),
                price=float(wc_product.get('price') or 0),
            )
            images = wc_product.get('images', [])
            if images:
                product.image_url = images[0].get('src', '')
            db.session.add(product)
            db.session.flush()
        
        product_id = product.id
        if not search_query:
            search_query = product.name
    
    if not product_id:
        return jsonify({'error': 'Product ID required'}), 400
    
    existing = Monitor.query.filter_by(product_id=product_id, source=source).first()
    if existing:
        return jsonify({'error': 'Monitor already exists for this product and source'}), 400
    
    monitor = Monitor(
        product_id=product_id,
        search_query=search_query,
        source=source,
        price_tolerance=data.get('price_tolerance', 50),
        is_active=True,
    )
    
    db.session.add(monitor)
    db.session.commit()
    
    return jsonify({'id': monitor.id, 'message': 'Monitor created'})

@api_bp.route('/monitors/bulk', methods=['POST'])
def bulk_create_monitors():
    data = request.json
    products = data.get('products', [])
    source = data.get('source', 'google_shopping')
    price_tolerance = data.get('price_tolerance', 50)
    
    created = 0
    skipped = 0
    
    for p in products:
        wc_product_id = p.get('wc_product_id')
        search_query = p.get('search_query', '')
        
        product = Product.query.filter_by(wc_product_id=wc_product_id).first()
        if not product:
            wc = WooCommerceService()
            wc_product = wc.get_product(wc_product_id)
            if not wc_product:
                skipped += 1
                continue
            
            product = Product(
                wc_product_id=wc_product_id,
                name=wc_product.get('name', ''),
                sku=wc_product.get('sku'),
                price=float(wc_product.get('price') or 0),
            )
            images = wc_product.get('images', [])
            if images:
                product.image_url = images[0].get('src', '')
            db.session.add(product)
            db.session.flush()
        
        existing = Monitor.query.filter_by(product_id=product.id, source=source).first()
        if existing:
            skipped += 1
            continue
        
        monitor = Monitor(
            product_id=product.id,
            search_query=search_query or product.name,
            source=source,
            price_tolerance=price_tolerance,
            is_active=True,
        )
        db.session.add(monitor)
        created += 1
    
    db.session.commit()
    
    return jsonify({'created': created, 'skipped': skipped})

@api_bp.route('/monitors/<int:monitor_id>', methods=['DELETE'])
def delete_monitor(monitor_id):
    monitor = Monitor.query.get_or_404(monitor_id)
    db.session.delete(monitor)
    db.session.commit()
    return jsonify({'message': 'Monitor deleted'})

@api_bp.route('/monitors/<int:monitor_id>', methods=['PUT', 'PATCH'])
def update_monitor(monitor_id):
    """Aggiorna un monitor (query, tolleranza, fonte, lingua)"""
    monitor = Monitor.query.get_or_404(monitor_id)
    data = request.json or {}
    
    if 'search_query' in data:
        monitor.search_query = data['search_query'][:500]
    if 'price_tolerance' in data:
        monitor.price_tolerance = float(data['price_tolerance'])
    if 'source' in data and data['source'] in ['all', 'both', 'google', 'google_shopping', 'google_web', 'ebay']:
        monitor.source = data['source']
    if 'language' in data:
        monitor.language = data['language']
    if 'is_active' in data:
        monitor.is_active = bool(data['is_active'])
    
    db.session.commit()
    return jsonify({'message': 'Monitor updated', 'monitor': monitor.to_dict()})

@api_bp.route('/monitors/bulk-update', methods=['POST'])
def bulk_update_monitors():
    """Aggiorna più monitor in batch"""
    data = request.json or {}
    monitor_ids = data.get('monitor_ids', [])
    updates = data.get('updates', {})
    
    if not monitor_ids:
        return jsonify({'error': 'No monitor IDs provided'}), 400
    
    updated = 0
    for monitor_id in monitor_ids:
        monitor = Monitor.query.get(monitor_id)
        if not monitor:
            continue
        
        if 'price_tolerance' in updates:
            monitor.price_tolerance = float(updates['price_tolerance'])
        if 'source' in updates and updates['source'] in ['all', 'both', 'google', 'google_shopping', 'google_web', 'ebay']:
            monitor.source = updates['source']
        if 'language' in updates:
            monitor.language = updates['language']
        if 'is_active' in updates:
            monitor.is_active = bool(updates['is_active'])
        
        updated += 1
    
    db.session.commit()
    return jsonify({'updated': updated, 'message': f'{updated} monitor aggiornati'})

@api_bp.route('/monitors/<int:monitor_id>/collect', methods=['POST'])
def collect_prices(monitor_id):
    monitor = Monitor.query.get_or_404(monitor_id)
    collector = PriceCollector()
    result = collector.collect_for_monitor(monitor)
    return jsonify(result)

@api_bp.route('/monitors/<int:monitor_id>/prices')
def get_monitor_prices(monitor_id):
    monitor = Monitor.query.get_or_404(monitor_id)
    show_all = request.args.get('show_all', 'false').lower() == 'true'
    
    # Prezzo di riferimento per filtrare outlier
    your_price = monitor.product.price if monitor.product else None
    
    # Calcola range ragionevole per escludere outlier
    # Se il tuo prezzo è €100, accettiamo da €70 a €180 (0.7x a 1.8x)
    min_reasonable = your_price * 0.70 if your_price else 0.01
    max_reasonable = your_price * 1.80 if your_price else 100000
    
    # Get prices - tutti o solo validi
    query = PriceRecord.query.filter_by(monitor_id=monitor_id)
    if not show_all:
        query = query.filter_by(is_valid=True)
    prices = query.order_by(PriceRecord.fetched_at.desc()).limit(100).all()
    
    # Se non ci sono validi, mostra tutti
    if len(prices) == 0 and not show_all:
        prices = PriceRecord.query.filter_by(
            monitor_id=monitor_id
        ).order_by(PriceRecord.fetched_at.desc()).limit(100).all()
    
    # Stats SOLO su record validi e con prezzo ragionevole (esclude outlier)
    stats_query = db.session.query(
        func.min(PriceRecord.price).label('min_price'),
        func.max(PriceRecord.price).label('max_price'),
        func.avg(PriceRecord.price).label('avg_price'),
        func.count(PriceRecord.id).label('total'),
        func.count(func.distinct(PriceRecord.seller_name)).label('sellers'),
    ).filter(
        PriceRecord.monitor_id == monitor_id,
        PriceRecord.is_valid == True,
        PriceRecord.price >= min_reasonable,
        PriceRecord.price <= max_reasonable
    )
    stats = stats_query.first()
    
    # Fallback: se non ci sono record validi nel range, usa tutti ma con filtro outlier
    if not stats.total or stats.total == 0:
        stats = db.session.query(
            func.min(PriceRecord.price).label('min_price'),
            func.max(PriceRecord.price).label('max_price'),
            func.avg(PriceRecord.price).label('avg_price'),
            func.count(PriceRecord.id).label('total'),
            func.count(func.distinct(PriceRecord.seller_name)).label('sellers'),
        ).filter(
            PriceRecord.monitor_id == monitor_id,
            PriceRecord.price >= min_reasonable,
            PriceRecord.price <= max_reasonable
        ).first()
    
    # Stats totali per confronto
    total_stats = db.session.query(
        func.count(PriceRecord.id).label('total_count'),
    ).filter(
        PriceRecord.monitor_id == monitor_id,
    ).first()
    
    valid_stats = db.session.query(
        func.count(PriceRecord.id).label('valid_count'),
    ).filter(
        PriceRecord.monitor_id == monitor_id,
        PriceRecord.is_valid == True
    ).first()
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    # History - solo record validi con filtro outlier
    history = db.session.query(
        func.date(PriceRecord.fetched_at).label('date'),
        func.min(PriceRecord.price).label('min_price'),
        func.avg(PriceRecord.price).label('avg_price'),
        func.max(PriceRecord.price).label('max_price'),
    ).filter(
        PriceRecord.monitor_id == monitor_id,
        PriceRecord.fetched_at >= thirty_days_ago,
        PriceRecord.is_valid == True,
        PriceRecord.price >= min_reasonable,
        PriceRecord.price <= max_reasonable
    ).group_by(func.date(PriceRecord.fetched_at)).order_by(func.date(PriceRecord.fetched_at)).all()
    
    # Fallback history senza filtro valid se vuoto
    if not history:
        history = db.session.query(
            func.date(PriceRecord.fetched_at).label('date'),
            func.min(PriceRecord.price).label('min_price'),
            func.avg(PriceRecord.price).label('avg_price'),
            func.max(PriceRecord.price).label('max_price'),
        ).filter(
            PriceRecord.monitor_id == monitor_id,
            PriceRecord.fetched_at >= thirty_days_ago,
            PriceRecord.price >= min_reasonable,
            PriceRecord.price <= max_reasonable
        ).group_by(func.date(PriceRecord.fetched_at)).order_by(func.date(PriceRecord.fetched_at)).all()
    
    return jsonify({
        'prices': [p.to_dict() for p in prices],
        'stats': {
            'min_price': float(stats.min_price) if stats.min_price else None,
            'max_price': float(stats.max_price) if stats.max_price else None,
            'avg_price': round(float(stats.avg_price), 2) if stats.avg_price else None,
            'total': stats.total if stats.total else 0,
            'total_all': total_stats.total_count if total_stats else 0,
            'valid_count': valid_stats.valid_count if valid_stats else 0,
            'sellers': stats.sellers if stats.sellers else 0,
            'outliers_excluded': (total_stats.total_count if total_stats else 0) - (stats.total if stats.total else 0),
        },
        'history': [
            {
                'date': str(h.date),
                'min_price': float(h.min_price),
                'avg_price': round(float(h.avg_price), 2),
                'max_price': float(h.max_price),
            }
            for h in history
        ],
        'your_price': monitor.product.price if monitor.product else None,
        'product_name': monitor.product.name if monitor.product else '',
        'search_query': monitor.search_query,
    })

@api_bp.route('/test-search', methods=['POST'])
def test_search():
    data = request.json
    source = data.get('source', 'all')  # Default: tutte e 3 le fonti
    query = data.get('query', '')
    filter_enabled = data.get('filter', True)
    language = data.get('language', 'it')
    
    if not query:
        return jsonify({'error': 'Query required'}), 400
    
    collector = PriceCollector()
    result = collector.test_search(source, query, filter_results=filter_enabled, language=language)
    
    return jsonify(result)

@api_bp.route('/collect-all', methods=['POST'])
def collect_all():
    """Raccoglie prezzi per un batch di monitor (max 5 per richiesta per evitare timeout)"""
    data = request.json or {}
    batch_size = min(data.get('batch_size', 5), 10)  # Max 10 per sicurezza
    offset = data.get('offset', 0)
    
    # Monitor attivi ordinati per ultima raccolta (prima quelli mai raccolti o più vecchi)
    monitors = Monitor.query.filter_by(is_active=True).order_by(
        Monitor.last_run_at.asc().nullsfirst()
    ).offset(offset).limit(batch_size).all()
    
    total_active = Monitor.query.filter_by(is_active=True).count()
    
    if not monitors:
        return jsonify({
            'processed': 0,
            'successful': 0,
            'failed': 0,
            'remaining': 0,
            'total': total_active,
            'message': 'Tutti i monitor sono stati processati'
        })
    
    collector = PriceCollector()
    
    results = {
        'processed': 0,
        'successful': 0,
        'failed': 0,
        'errors': [],
    }
    
    for monitor in monitors:
        try:
            print(f"[Collect] Processing monitor {monitor.id}: {monitor.search_query[:50]}...")
            result = collector.collect_for_monitor(monitor)
            results['processed'] += 1
            
            # Aggiorna timestamp ultima raccolta
            monitor.last_run_at = datetime.utcnow()
            db.session.commit()
            
            if 'error' in result:
                results['failed'] += 1
                results['errors'].append(f"Monitor {monitor.id}: {result['error']}")
            else:
                results['successful'] += 1
                print(f"[Collect] Monitor {monitor.id}: {result.get('new_records', 0)} nuovi record")
        except Exception as e:
            results['failed'] += 1
            results['errors'].append(f"Monitor {monitor.id}: {str(e)}")
            print(f"[Collect] Error on monitor {monitor.id}: {e}")
    
    remaining = total_active - offset - len(monitors)
    results['remaining'] = max(0, remaining)
    results['total'] = total_active
    results['next_offset'] = offset + len(monitors)
    
    if remaining > 0:
        results['message'] = f'Processati {results["processed"]}, rimangono {remaining} monitor'
    else:
        results['message'] = f'Completato! Processati {results["processed"]} monitor'
    
    return jsonify(results)


@api_bp.route('/monitors/cleanup-single-cards', methods=['POST'])
def cleanup_single_cards():
    """Elimina TUTTI i dati delle carte singole: monitor, price records E prodotti"""
    
    # 1. Trova tutti i prodotti che sono carte singole
    products = Product.query.all()
    single_card_products = [p for p in products if is_single_card(p.name)]
    
    deleted_monitors = 0
    deleted_products = 0
    deleted_records = 0
    
    for product in single_card_products:
        # 2. Elimina tutti i monitor associati
        monitors = Monitor.query.filter_by(product_id=product.id).all()
        for monitor in monitors:
            # 3. Elimina tutti i price records
            records_count = PriceRecord.query.filter_by(monitor_id=monitor.id).delete()
            deleted_records += records_count
            db.session.delete(monitor)
            deleted_monitors += 1
        
        # 4. Elimina il prodotto
        db.session.delete(product)
        deleted_products += 1
    
    db.session.commit()
    
    return jsonify({
        'deleted_monitors': deleted_monitors,
        'deleted_products': deleted_products,
        'deleted_records': deleted_records,
        'message': f'Eliminati {deleted_products} carte singole, {deleted_monitors} monitor, {deleted_records} prezzi'
    })

@api_bp.route('/monitors/create-all', methods=['POST'])
def create_monitors_for_all():
    """Crea UN monitor per ogni prodotto SEALED disponibile (esclude carte singole)"""
    try:
        data = request.get_json(silent=True) or {}
    except:
        data = {}
    price_tolerance = data.get('price_tolerance', 50)
    language = data.get('language', 'it')
    
    # Prendi tutti i prodotti in stock dal database locale
    products = Product.query.filter_by(stock_status='instock').all()
    
    if not products:
        return jsonify({
            'error': 'Nessun prodotto disponibile trovato',
            'message': 'Sincronizza prima i prodotti da WooCommerce',
            'created': 0
        })
    
    created = 0
    skipped = 0
    skipped_single_cards = 0
    
    for product in products:
        # ESCLUDI carte singole per risparmiare API
        if is_single_card(product.name):
            skipped_single_cards += 1
            continue
        
        # Controlla se esiste già un monitor per questo prodotto
        existing = Monitor.query.filter_by(product_id=product.id).first()
        if existing:
            skipped += 1
            continue
        
        # Crea UN monitor che cerca su ENTRAMBE le fonti
        monitor = Monitor(
            product_id=product.id,
            search_query=product.name,
            source='all',  # Cerca su tutte e 3 le fonti
            language=language,
            price_tolerance=price_tolerance,
            is_active=True,
        )
        db.session.add(monitor)
        created += 1
    
    db.session.commit()
    
    return jsonify({
        'created': created,
        'skipped': skipped,
        'skipped_single_cards': skipped_single_cards,
        'total_products': len(products),
        'message': f'Creati {created} monitor sealed (escluse {skipped_single_cards} carte singole)'
    })
