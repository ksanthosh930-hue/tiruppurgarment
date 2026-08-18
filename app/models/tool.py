from datetime import datetime
from app import db

class ToolCategory(db.Model):
    __tablename__ = 'tool_categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<ToolCategory {self.name}>'


class Tool(db.Model):
    __tablename__ = 'tools'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    
    category_id = db.Column(db.Integer, db.ForeignKey('tool_categories.id', ondelete='SET NULL'), index=True)
    
    status = db.Column(db.String(20), default='published', nullable=False, index=True) # draft, published, archived
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # SEO fields
    seo_title = db.Column(db.String(150))
    seo_description = db.Column(db.String(255))
    
    # Relationships
    category = db.relationship('ToolCategory', backref=db.backref('tools', lazy='dynamic'))

    def __repr__(self):
        return f'<Tool {self.name}>'
        return f'<Tool {self.name_en}>'
