from flask import Blueprint, render_template, current_app

main_bp = Blueprint('main', __name__)

def get_sources_configured():
    return {
        'google_shopping': bool(current_app.config.get('SERPAPI_KEY')),
        'ebay': bool(current_app.config.get('EBAY_CLIENT_ID') and current_app.config.get('EBAY_CLIENT_SECRET')),
        'woocommerce': bool(current_app.config.get('WC_URL') and current_app.config.get('WC_CONSUMER_KEY')),
    }

@main_bp.route('/')
def dashboard():
    from app.models import Product, Monitor, PriceRecord
    
    total_products = Product.query.count()
    total_monitors = Monitor.query.count()
    active_monitors = Monitor.query.filter_by(is_active=True).count()
    total_records = PriceRecord.query.count()
    
    # Semplice - niente analisi pesante per ora
    competitive_data = {
        'best': 0, 'average': 0, 'high': 0, 'no_data': active_monitors,
        'best_pct': 0, 'average_pct': 0, 'high_pct': 0
    }
    
    # Solo ultimi 5 monitor senza analisi complessa
    recent_monitors = Monitor.query.order_by(Monitor.created_at.desc()).limit(5).all()
    
    return render_template('dashboard.html',
        total_products=total_products,
        total_monitors=total_monitors,
        active_monitors=active_monitors,
        total_records=total_records,
        sources_configured=get_sources_configured(),
        competitive_data=competitive_data,
        monitors_analysis=[],
        recent_monitors=recent_monitors,
    )

@main_bp.route('/products')
def products():
    return render_template('products.html', sources_configured=get_sources_configured())

@main_bp.route('/monitors')
def monitors():
    from app.models import Monitor
    monitors_list = Monitor.query.order_by(Monitor.created_at.desc()).limit(50).all()
    return render_template('monitors.html', monitors=monitors_list, sources_configured=get_sources_configured())

@main_bp.route('/settings')
def settings():
    return render_template('settings.html', sources_configured=get_sources_configured())
