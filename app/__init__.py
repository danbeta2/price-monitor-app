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
    
    from app.routes import main_bp
    app.register_blueprint(main_bp)
    
    from app.api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    
    return app
