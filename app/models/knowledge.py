from datetime import datetime
from app import db
from app.models.news import Tag

# Association table for Knowledge Articles and Tags
knowledge_tags = db.Table('knowledge_tags',
    db.Column('knowledge_id', db.Integer, db.ForeignKey('knowledge_articles.id', ondelete='CASCADE'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True)
)

class KnowledgeCategory(db.Model):
    __tablename__ = 'knowledge_categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<KnowledgeCategory {self.name}>'


class KnowledgeArticle(db.Model):
    __tablename__ = 'knowledge_articles'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    summary = db.Column(db.Text, nullable=False)
    content = db.Column(db.Text, nullable=False)
    featured_image = db.Column(db.String(255))
    
    category_id = db.Column(db.Integer, db.ForeignKey('knowledge_categories.id', ondelete='SET NULL'), index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    
    status = db.Column(db.String(20), default='draft', nullable=False, index=True) # draft, review, published, archived
    
    published_at = db.Column(db.DateTime, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # SEO fields
    seo_title = db.Column(db.String(150))
    seo_description = db.Column(db.String(255))
    canonical_url = db.Column(db.String(255))
    
    # Relationships
    category = db.relationship('KnowledgeCategory', backref=db.backref('articles', lazy='dynamic'))
    author = db.relationship('User', backref=db.backref('knowledge_articles', lazy='dynamic'))
    tags = db.relationship('Tag', secondary=knowledge_tags, backref=db.backref('knowledge_articles', lazy='dynamic'))

    def __repr__(self):
        return f'<KnowledgeArticle {self.title}>'
        return f'<KnowledgeArticle {self.title_en}>'
