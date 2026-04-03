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
        except Exception as e:
            print(f"[Migration] Warning: {e}")
    
    from app.routes import main_bp
    app.register_blueprint(main_bp)
    
    from app.api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    
    return app
