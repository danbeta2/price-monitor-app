from flask import Blueprint, render_template, current_app

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def dashboard():
    from app.models import Product, Monitor, PriceRecord
    from app import db
    from sqlalchemy import func
    from datetime import datetime, timedelta
    
    total_products = Product.query.count()
    total_monitors = Monitor.query.count()
    active_monitors = Monitor.query.filter_by(is_active=True).count()
    total_records = PriceRecord.query.filter_by(is_valid=True).count()
    
    sources_configured = {
        'google_shopping': bool(current_app.config.get('SERPAPI_KEY')),
        'ebay': bool(current_app.config.get('EBAY_CLIENT_ID') and current_app.config.get('EBAY_CLIENT_SECRET')),
        'woocommerce': bool(current_app.config.get('WC_URL') and current_app.config.get('WC_CONSUMER_KEY')),
    }
    
    # Calcola competitività per ogni monitor
    competitive_data = {'best': 0, 'average': 0, 'high': 0, 'no_data': 0}
    monitors_with_analysis = []
    
    monitors = Monitor.query.filter_by(is_active=True).all()
    
    for monitor in monitors:
        your_price = monitor.product.price if monitor.product else None
        
        # Prendi il prezzo minimo dei competitor (ultimi 7 giorni)
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        min_competitor = db.session.query(func.min(PriceRecord.price)).filter(
            PriceRecord.monitor_id == monitor.id,
            PriceRecord.is_valid == True,
            PriceRecord.fetched_at >= seven_days_ago
        ).scalar()
        
        avg_competitor = db.session.query(func.avg(PriceRecord.price)).filter(
            PriceRecord.monitor_id == monitor.id,
            PriceRecord.is_valid == True,
            PriceRecord.fetched_at >= seven_days_ago
        ).scalar()
        
        record_count = PriceRecord.query.filter(
            PriceRecord.monitor_id == monitor.id,
            PriceRecord.is_valid == True
        ).count()
        
        analysis = {
            'monitor': monitor,
            'your_price': your_price,
            'min_price': float(min_competitor) if min_competitor else None,
            'avg_price': round(float(avg_competitor), 2) if avg_competitor else None,
            'record_count': record_count,
            'status': 'no_data',
            'diff_percent': None,
        }
        
        if your_price and min_competitor:
            diff = ((your_price - min_competitor) / min_competitor) * 100
            analysis['diff_percent'] = round(diff, 1)
            
            if diff <= -5:
                analysis['status'] = 'best'
                competitive_data['best'] += 1
            elif diff <= 10:
                analysis['status'] = 'average'
                competitive_data['average'] += 1
            else:
                analysis['status'] = 'high'
                competitive_data['high'] += 1
        else:
            competitive_data['no_data'] += 1
        
        monitors_with_analysis.append(analysis)
    
    # Ordina per status (high first, then average, then best)
    status_order = {'high': 0, 'average': 1, 'best': 2, 'no_data': 3}
    monitors_with_analysis.sort(key=lambda x: (status_order.get(x['status'], 4), -(x['diff_percent'] or 0)))
    
    # Calcola percentuali per la barra
    total_with_data = competitive_data['best'] + competitive_data['average'] + competitive_data['high']
    if total_with_data > 0:
        competitive_data['best_pct'] = round((competitive_data['best'] / total_with_data) * 100)
        competitive_data['average_pct'] = round((competitive_data['average'] / total_with_data) * 100)
        competitive_data['high_pct'] = round((competitive_data['high'] / total_with_data) * 100)
    else:
        competitive_data['best_pct'] = 0
        competitive_data['average_pct'] = 0
        competitive_data['high_pct'] = 0
    
    return render_template('dashboard.html',
        total_products=total_products,
        total_monitors=total_monitors,
        active_monitors=active_monitors,
        total_records=total_records,
        sources_configured=sources_configured,
        competitive_data=competitive_data,
        monitors_analysis=monitors_with_analysis[:10],  # Top 10
    )

@main_bp.route('/products')
def products():
    return render_template('products.html')

@main_bp.route('/monitors')
def monitors():
    from app.models import Monitor
    monitors = Monitor.query.order_by(Monitor.created_at.desc()).all()
    return render_template('monitors.html', monitors=monitors)

@main_bp.route('/settings')
def settings():
    sources_configured = {
        'google_shopping': bool(current_app.config['SERPAPI_KEY']),
        'ebay': bool(current_app.config['EBAY_CLIENT_ID'] and current_app.config['EBAY_CLIENT_SECRET']),
        'woocommerce': bool(current_app.config['WC_URL'] and current_app.config['WC_CONSUMER_KEY']),
    }
    return render_template('settings.html', sources_configured=sources_configured)
