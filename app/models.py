from datetime import datetime
from app import db

class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    wc_product_id = db.Column(db.Integer, unique=True, nullable=False)
    name = db.Column(db.String(500), nullable=False)
    sku = db.Column(db.String(100))
    price = db.Column(db.Float)
    image_url = db.Column(db.String(1000))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    monitors = db.relationship('Monitor', backref='product', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'wc_product_id': self.wc_product_id,
            'name': self.name,
            'sku': self.sku,
            'price': self.price,
            'image_url': self.image_url,
        }


class Monitor(db.Model):
    __tablename__ = 'monitors'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    search_query = db.Column(db.String(500), nullable=False)
    source = db.Column(db.String(50), default='google_shopping')
    price_tolerance = db.Column(db.Float, default=50.0)
    is_active = db.Column(db.Boolean, default=True)
    last_run_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    price_records = db.relationship('PriceRecord', backref='monitor', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'search_query': self.search_query,
            'source': self.source,
            'price_tolerance': self.price_tolerance,
            'is_active': self.is_active,
            'last_run_at': self.last_run_at.isoformat() if self.last_run_at else None,
        }


class PriceRecord(db.Model):
    __tablename__ = 'price_records'
    
    id = db.Column(db.Integer, primary_key=True)
    monitor_id = db.Column(db.Integer, db.ForeignKey('monitors.id'), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    price = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), default='EUR')
    seller_name = db.Column(db.String(255))
    seller_rating = db.Column(db.Float)
    url = db.Column(db.String(2000))
    source = db.Column(db.String(50))
    is_valid = db.Column(db.Boolean, default=True)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'price': self.price,
            'currency': self.currency,
            'seller_name': self.seller_name,
            'seller_rating': self.seller_rating,
            'url': self.url,
            'source': self.source,
            'is_valid': self.is_valid,
            'fetched_at': self.fetched_at.isoformat() if self.fetched_at else None,
        }
