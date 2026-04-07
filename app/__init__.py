from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from config import Config

db = SQLAlchemy()

def create_app():
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config.from_object(Config)
    
    db.init_app(app)
    
    with app.app_context():
        from app import models
        db.create_all()
        
        # Migrazione manuale: aggiungi colonne mancanti
        try:
            from sqlalchemy import text
            with db.engine.connect() as conn:
                # Aggiungi user_feedback a price_records se non esiste
                try:
                    conn.execute(text("ALTER TABLE price_records ADD COLUMN user_feedback BOOLEAN"))
                    conn.commit()
                    print("[Migration] Added user_feedback column to price_records")
                except Exception:
                    pass  # Colonna già esistente

                # Crea indici per performance query price_records
                for idx_name, idx_sql in [
                    ('idx_price_monitor_valid', 'CREATE INDEX IF NOT EXISTS idx_price_monitor_valid ON price_records (monitor_id, is_valid)'),
                    ('idx_price_monitor_date', 'CREATE INDEX IF NOT EXISTS idx_price_monitor_date ON price_records (monitor_id, fetched_at)'),
                    ('idx_price_monitor_valid_price', 'CREATE INDEX IF NOT EXISTS idx_price_monitor_valid_price ON price_records (monitor_id, is_valid, price)'),
                ]:
                    try:
                        conn.execute(text(idx_sql))
                        conn.commit()
                    except Exception:
                        pass  # Indice già esistente
                # Aggiorna tolerance: forza max 40% per tutti i monitor
                try:
                    result = conn.execute(text(
                        "UPDATE monitors SET price_tolerance = 40 WHERE price_tolerance > 40 OR price_tolerance IS NULL"
                    ))
                    conn.commit()
                    if result.rowcount > 0:
                        print(f"[Migration] Updated {result.rowcount} monitors: tolerance -> 40%")
                except Exception:
                    pass

                # Invalida price_records fuori dal range ±40% del prezzo prodotto
                try:
                    result = conn.execute(text("""
                        UPDATE price_records SET is_valid = false
                        WHERE is_valid = true AND id IN (
                            SELECT pr.id FROM price_records pr
                            JOIN monitors m ON pr.monitor_id = m.id
                            JOIN products p ON m.product_id = p.id
                            WHERE pr.is_valid = true
                            AND p.price > 0
                            AND (pr.price < p.price * 0.6 OR pr.price > p.price * 1.4)
                        )
                    """))
                    conn.commit()
                    if result.rowcount > 0:
                        print(f"[Migration] Invalidated {result.rowcount} price records outside ±40% range")
                except Exception as e:
                    print(f"[Migration] Price cleanup warning: {e}")

                # Invalida record che contengono keyword negative (salvati prima dei fix)
                negative_keywords = [
                    'lotto', 'lotti', 'lot ', ' lot',
                    '2x', '3x', '4x', '5x',
                    'x2 ', 'x3 ', 'x4 ', 'x5 ',
                    'empty', 'vuoto', 'vuota',
                    'fake', 'replica', 'proxy', 'repack', 'resealed',
                    'psa ', 'bgs ', 'cgc ', 'graded',
                    'sleeves', 'playmat', 'toploader', 'binder',
                    'ultra pro', 'dragon shield', 'gamegenic',
                    'singola', 'singolo', 'single card',
                    'poster', 'album foto', 'raccoglitore',
                ]
                try:
                    # Costruisci WHERE con OR per ogni keyword
                    conditions = " OR ".join(
                        f"LOWER(title) LIKE :kw{i}" for i in range(len(negative_keywords))
                    )
                    params = {f"kw{i}": f"%{kw}%" for i, kw in enumerate(negative_keywords)}
                    result = conn.execute(text(
                        f"UPDATE price_records SET is_valid = false WHERE is_valid = true AND ({conditions})"
                    ), params)
                    conn.commit()
                    if result.rowcount > 0:
                        print(f"[Migration] Invalidated {result.rowcount} records with negative keywords")
                except Exception as e:
                    print(f"[Migration] Negative keyword cleanup warning: {e}")

                # Pulisci record del proprio negozio dai competitor
                import re as re_mod
                wc_url = app.config.get('WC_URL', '')
                if wc_url:
                    match_url = re_mod.search(r'://(?:www\.)?([^/]+)', wc_url)
                    if match_url:
                        domain = match_url.group(1).lower()
                        domain_short = domain.split('.')[0]
                        try:
                            result = conn.execute(text(
                                "DELETE FROM price_records WHERE LOWER(seller_name) LIKE :d1 OR LOWER(seller_name) LIKE :d2 OR LOWER(url) LIKE :d3 OR LOWER(url) LIKE :d4"
                            ), {'d1': f'%{domain}%', 'd2': f'%{domain_short}%', 'd3': f'%{domain}%', 'd4': f'%{domain_short}%'})
                            conn.commit()
                            if result.rowcount > 0:
                                print(f"[Migration] Removed {result.rowcount} own-store records ({domain})")
                        except Exception as e2:
                            print(f"[Migration] Own-store cleanup warning: {e2}")
                else:
                    # Fallback: cerca "scimmia" direttamente se WC_URL non configurato
                    try:
                        result = conn.execute(text(
                            "DELETE FROM price_records WHERE LOWER(seller_name) LIKE '%scimmia%' OR LOWER(url) LIKE '%scimmia%'"
                        ))
                        conn.commit()
                        if result.rowcount > 0:
                            print(f"[Migration] Removed {result.rowcount} own-store records (scimmia fallback)")
                    except Exception as e2:
                        print(f"[Migration] Own-store cleanup warning: {e2}")

        except Exception as e:
            print(f"[Migration] Warning: {e}")

    from app.routes import main_bp
    app.register_blueprint(main_bp)
    
    from app.api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    
    return app
