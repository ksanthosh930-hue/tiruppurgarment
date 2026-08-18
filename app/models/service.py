from datetime import datetime
from app import db

class Service(db.Model):
    __tablename__ = 'services'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    
    provider_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    
    status = db.Column(db.String(20), default='published', nullable=False, index=True) # draft, published, archived
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    provider = db.relationship('Company', backref=db.backref('services', lazy='dynamic', cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<Service {self.name}>'
