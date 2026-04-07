from flask import Blueprint, render_template, current_app
from sqlalchemy import func
from datetime import datetime, timedelta

main_bp = Blueprint('main', __name__)

# Tolerance massima usata per il calcolo dashboard (cap forzato)
MAX_TOLERANCE = 40

def get_sources_configured():
    return {
        'google_shopping': bool(current_app.config.get('SERPAPI_KEY')),
        'ebay': bool(current_app.config.get('EBAY_CLIENT_ID') and current_app.config.get('EBAY_CLIENT_SECRET')),
        'woocommerce': bool(current_app.config.get('WC_URL') and current_app.config.get('WC_CONSUMER_KEY')),
    }

@main_bp.route('/')
def dashboard():
    from app import db
    from app.models import Product, Monitor, PriceRecord

    total_products = Product.query.count()
    total_monitors = Monitor.query.count()
    active_monitors = Monitor.query.filter_by(is_active=True).count()
    total_records = PriceRecord.query.count()

    # Analisi competitiva reale: confronta il tuo prezzo con la media mercato
    best = 0    # Tuo prezzo <= miglior prezzo competitor (+5%)
    average = 0  # Tuo prezzo nella media (entro ±10%)
    high = 0     # Tuo prezzo sopra la media (>10%)
    no_data = 0

    monitors_with_product = Monitor.query.filter_by(is_active=True).all()
    cutoff_date = datetime.utcnow() - timedelta(days=30)
    for m in monitors_with_product:
        if not m.product or not m.product.price:
            no_data += 1
            continue

        your_price = m.product.price
        tolerance_pct = min(MAX_TOLERANCE, m.price_tolerance if m.price_tolerance and m.price_tolerance > 0 else MAX_TOLERANCE)
        min_r = your_price * (1 - tolerance_pct / 100)
        max_r = your_price * (1 + tolerance_pct / 100)

        avg_result = db.session.query(
            func.avg(PriceRecord.price)
        ).filter(
            PriceRecord.monitor_id == m.id,
            PriceRecord.is_valid == True,
            PriceRecord.price >= min_r,
            PriceRecord.price <= max_r,
            PriceRecord.fetched_at >= cutoff_date,
        ).scalar()

        if avg_result is None:
            no_data += 1
            continue

        avg_market = float(avg_result)
        if your_price <= avg_market * 1.05:
            best += 1
        elif your_price <= avg_market * 1.10:
            average += 1
        else:
            high += 1

    total_with_data = best + average + high
    competitive_data = {
        'best': best, 'average': average, 'high': high, 'no_data': no_data,
        'best_pct': round(best / total_with_data * 100) if total_with_data else 0,
        'average_pct': round(average / total_with_data * 100) if total_with_data else 0,
        'high_pct': round(high / total_with_data * 100) if total_with_data else 0,
    }

    # Prodotti da tenere sotto controllo: troppo alti o troppo bassi vs mercato
    price_too_high = []   # Tuo prezzo >15% sopra la media
    price_too_low = []    # Tuo prezzo >10% sotto la media

    for m in monitors_with_product:
        if not m.product or not m.product.price:
            continue

        your_price = m.product.price
        tolerance_pct = min(MAX_TOLERANCE, m.price_tolerance if m.price_tolerance and m.price_tolerance > 0 else MAX_TOLERANCE)
        min_r = your_price * (1 - tolerance_pct / 100)
        max_r = your_price * (1 + tolerance_pct / 100)

        stats = db.session.query(
            func.avg(PriceRecord.price).label('avg'),
            func.min(PriceRecord.price).label('min'),
        ).filter(
            PriceRecord.monitor_id == m.id,
            PriceRecord.is_valid == True,
            PriceRecord.price >= min_r,
            PriceRecord.price <= max_r,
            PriceRecord.fetched_at >= cutoff_date,
        ).first()

        if not stats.avg:
            continue

        avg_market = float(stats.avg)
        min_market = float(stats.min)
        diff_pct = round((your_price - avg_market) / avg_market * 100, 1)

        item = {
            'name': m.product.name,
            'your_price': your_price,
            'avg_market': round(avg_market, 2),
            'min_market': round(min_market, 2),
            'diff_pct': diff_pct,
            'monitor_id': m.id,
        }

        if diff_pct > 15:
            price_too_high.append(item)
        elif diff_pct < -10:
            price_too_low.append(item)

    # Ordina: piu critico prima
    price_too_high.sort(key=lambda x: -x['diff_pct'])
    price_too_low.sort(key=lambda x: x['diff_pct'])

    return render_template('dashboard.html',
        total_products=total_products,
        total_monitors=total_monitors,
        active_monitors=active_monitors,
        total_records=total_records,
        sources_configured=get_sources_configured(),
        competitive_data=competitive_data,
        price_too_high=price_too_high[:10],
        price_too_low=price_too_low[:10],
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
