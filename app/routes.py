from flask import Blueprint, render_template, current_app

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def dashboard():
    from app.models import Product, Monitor, PriceRecord
    from sqlalchemy import func
    
    total_products = Product.query.count()
    total_monitors = Monitor.query.count()
    active_monitors = Monitor.query.filter_by(is_active=True).count()
    total_records = PriceRecord.query.filter_by(is_valid=True).count()
    
    recent_monitors = Monitor.query.order_by(Monitor.last_run_at.desc()).limit(10).all()
    
    sources_configured = {
        'google_shopping': bool(current_app.config['SERPAPI_KEY']),
        'ebay': bool(current_app.config['EBAY_CLIENT_ID'] and current_app.config['EBAY_CLIENT_SECRET']),
    }
    
    return render_template('dashboard.html',
        total_products=total_products,
        total_monitors=total_monitors,
        active_monitors=active_monitors,
        total_records=total_records,
        recent_monitors=recent_monitors,
        sources_configured=sources_configured,
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
