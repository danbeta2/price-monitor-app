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
                # Pulisci record del proprio negozio dai competitor
                import re
                wc_url = app.config.get('WC_URL', '')
                if wc_url:
                    match = re.search(r'://(?:www\.)?([^/]+)', wc_url)
                    if match:
                        domain = match.group(1).lower()
                        domain_short = domain.split('.')[0]
                        try:
                            result = conn.execute(text(
                                "DELETE FROM price_records WHERE LOWER(seller_name) LIKE :d1 OR LOWER(seller_name) LIKE :d2"
                            ), {'d1': f'%{domain}%', 'd2': f'%{domain_short}%'})
                            conn.commit()
                            if result.rowcount > 0:
                                print(f"[Migration] Removed {result.rowcount} own-store records ({domain})")
                        except Exception as e2:
                            print(f"[Migration] Own-store cleanup warning: {e2}")

        except Exception as e:
            print(f"[Migration] Warning: {e}")

    from app.routes import main_bp
    app.register_blueprint(main_bp)
    
    from app.api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    
    return app
