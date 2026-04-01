from flask import Blueprint, jsonify, request
from app import db
from app.models import Product, Monitor, PriceRecord
from app.services.woocommerce import WooCommerceService
from app.services.price_collector import PriceCollector
from sqlalchemy import func
from datetime import datetime, timedelta

api_bp = Blueprint('api', __name__)

@api_bp.route('/products')
def get_products():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    category = request.args.get('category', type=int)
    search = request.args.get('search', '')
    in_stock_only = request.args.get('in_stock_only', 'false').lower() == 'true'
    
    wc = WooCommerceService()
    products = wc.get_products(page=page, per_page=per_page, category=category, search=search, in_stock_only=in_stock_only)
    
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
    
    page = 1
    synced = 0
    in_stock = 0
    out_of_stock = 0
    
    # Prima chiamata per verificare la connessione
    print("[Sync] Starting sync...")
    first_batch = wc.get_products(page=1, per_page=50)
    print(f"[Sync] First batch: {type(first_batch)}, length: {len(first_batch) if first_batch else 'None'}")
    
    if first_batch is None:
        return jsonify({
            'error': 'Errore connessione WooCommerce',
            'details': wc.last_error or 'Impossibile connettersi a WooCommerce API',
            'synced': 0
        }), 500
    
    if not first_batch:
        return jsonify({
            'synced': 0,
            'in_stock': 0,
            'out_of_stock': 0,
            'message': 'Nessun prodotto trovato su WooCommerce (lista vuota)'
        })
    
    # Processa prima batch
    products_to_process = [first_batch]
    
    # Carica altre pagine se necessario
    if len(first_batch) == 50:
        page = 2
        while True:
            more_products = wc.get_products(page=page, per_page=50)
            if not more_products:
                break
            products_to_process.append(more_products)
            page += 1
            if len(more_products) < 50:
                break
    
    # Processa tutti i prodotti
    try:
        for batch in products_to_process:
            for wc_product in batch:
                product = Product.query.filter_by(wc_product_id=wc_product['id']).first()
                
                if not product:
                    product = Product(wc_product_id=wc_product['id'])
                    db.session.add(product)
                
                product.name = wc_product.get('name', '')[:500]
                product.sku = wc_product.get('sku', '')[:100] if wc_product.get('sku') else None
                product.price = float(wc_product.get('price') or 0)
                product.stock_status = wc_product.get('stock_status', 'instock')
                product.stock_quantity = wc_product.get('stock_quantity') or 0
                
                if product.stock_status == 'instock':
                    in_stock += 1
                else:
                    out_of_stock += 1
                
                images = wc_product.get('images', [])
                if images:
                    product.image_url = images[0].get('src', '')[:1000]
                
                synced += 1
        
        db.session.commit()
        print(f"[Sync] Completed: {synced} synced, {in_stock} in stock, {out_of_stock} out of stock")
        
        return jsonify({
            'synced': synced,
            'in_stock': in_stock,
            'out_of_stock': out_of_stock,
        })
    except Exception as e:
        db.session.rollback()
        print(f"[Sync] Error: {str(e)}")
        return jsonify({
            'error': 'Errore durante la sincronizzazione',
            'details': str(e),
            'synced': 0
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
    
    # Get prices - tutti o solo validi
    query = PriceRecord.query.filter_by(monitor_id=monitor_id)
    if not show_all:
        query = query.filter_by(is_valid=True)
    prices = query.order_by(PriceRecord.fetched_at.desc()).limit(50).all()
    
    # Se non ci sono validi, mostra tutti
    if len(prices) == 0 and not show_all:
        prices = PriceRecord.query.filter_by(
            monitor_id=monitor_id
        ).order_by(PriceRecord.fetched_at.desc()).limit(50).all()
    
    # Stats su tutti i record (non solo validi) per avere sempre dati
    stats = db.session.query(
        func.min(PriceRecord.price).label('min_price'),
        func.max(PriceRecord.price).label('max_price'),
        func.avg(PriceRecord.price).label('avg_price'),
        func.count(PriceRecord.id).label('total'),
        func.count(func.distinct(PriceRecord.seller_name)).label('sellers'),
    ).filter(
        PriceRecord.monitor_id == monitor_id
    ).first()
    
    # Stats solo validi per confronto
    valid_stats = db.session.query(
        func.count(PriceRecord.id).label('valid_count'),
    ).filter(
        PriceRecord.monitor_id == monitor_id,
        PriceRecord.is_valid == True
    ).first()
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    # History - prova prima con solo validi, poi tutti
    history = db.session.query(
        func.date(PriceRecord.fetched_at).label('date'),
        func.min(PriceRecord.price).label('min_price'),
        func.avg(PriceRecord.price).label('avg_price'),
        func.max(PriceRecord.price).label('max_price'),
    ).filter(
        PriceRecord.monitor_id == monitor_id,
        PriceRecord.fetched_at >= thirty_days_ago,
    ).group_by(func.date(PriceRecord.fetched_at)).order_by(func.date(PriceRecord.fetched_at)).all()
    
    return jsonify({
        'prices': [p.to_dict() for p in prices],
        'stats': {
            'min_price': float(stats.min_price) if stats.min_price else None,
            'max_price': float(stats.max_price) if stats.max_price else None,
            'avg_price': round(float(stats.avg_price), 2) if stats.avg_price else None,
            'total': stats.total,
            'valid_count': valid_stats.valid_count if valid_stats else 0,
            'sellers': stats.sellers,
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
    source = data.get('source', 'both')  # Default: entrambe le fonti
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
    monitors = Monitor.query.filter_by(is_active=True).all()
    collector = PriceCollector()
    
    results = {
        'processed': 0,
        'successful': 0,
        'failed': 0,
    }
    
    for monitor in monitors:
        result = collector.collect_for_monitor(monitor)
        results['processed'] += 1
        
        if 'error' in result:
            results['failed'] += 1
        else:
            results['successful'] += 1
    
    return jsonify(results)


@api_bp.route('/monitors/create-all', methods=['POST'])
def create_monitors_for_all():
    """Crea UN monitor per ogni prodotto disponibile (cerca su Google + eBay insieme)"""
    data = request.json or {}
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
    
    for product in products:
        # Controlla se esiste già un monitor per questo prodotto
        existing = Monitor.query.filter_by(product_id=product.id).first()
        if existing:
            skipped += 1
            continue
        
        # Crea UN monitor che cerca su ENTRAMBE le fonti
        monitor = Monitor(
            product_id=product.id,
            search_query=product.name,
            source='both',  # Cerca su Google + eBay
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
        'total_products': len(products),
        'message': f'Creati {created} monitor (ogni monitor cerca su Google + eBay)'
    })
