from datetime import datetime
from app import db

class CompanyCategory(db.Model):
    __tablename__ = 'company_categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<CompanyCategory {self.name}>'


class Company(db.Model):
    __tablename__ = 'companies'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    logo = db.Column(db.String(255))
    
    category_id = db.Column(db.Integer, db.ForeignKey('company_categories.id', ondelete='SET NULL'), index=True)
    
    website = db.Column(db.String(255))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(50))
    address = db.Column(db.Text)
    
    status = db.Column(db.String(20), default='published', nullable=False, index=True) # draft, published, archived
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # SEO fields
    seo_title = db.Column(db.String(150))
    seo_description = db.Column(db.String(255))
    
    # Relationships
    category = db.relationship('CompanyCategory', backref=db.backref('companies', lazy='dynamic'))

    def __repr__(self):
        return f'<Company {self.name}>'
        return f'<Company {self.name_en}>'
