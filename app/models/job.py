from datetime import datetime
from app import db

class Job(db.Model):
    __tablename__ = 'jobs'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    
    location = db.Column(db.String(150), nullable=False)
    salary_range = db.Column(db.String(100))
    job_type = db.Column(db.String(50)) # e.g. Full-time, Part-time, Contract
    
    status = db.Column(db.String(20), default='published', nullable=False, index=True) # draft, published, archived
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # SEO fields
    seo_title = db.Column(db.String(150))
    seo_description = db.Column(db.String(255))
    
    # Relationships
    company = db.relationship('Company', backref=db.backref('jobs', lazy='dynamic', cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<Job {self.title}>'
