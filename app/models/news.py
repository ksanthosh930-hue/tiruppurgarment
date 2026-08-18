from datetime import datetime
from app import db

# Association table for News Articles and Tags
news_tags = db.Table('news_tags',
    db.Column('news_id', db.Integer, db.ForeignKey('news_articles.id', ondelete='CASCADE'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True)
)

class Tag(db.Model):
    __tablename__ = 'tags'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<Tag {self.name}>'


class NewsCategory(db.Model):
    __tablename__ = 'news_categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<NewsCategory {self.name}>'


class NewsArticle(db.Model):
    __tablename__ = 'news_articles'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    summary = db.Column(db.Text, nullable=False)
    content = db.Column(db.Text, nullable=False)
    featured_image = db.Column(db.String(255))
    
    category_id = db.Column(db.Integer, db.ForeignKey('news_categories.id', ondelete='SET NULL'), index=True)
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
    category = db.relationship('NewsCategory', backref=db.backref('articles', lazy='dynamic'))
    author = db.relationship('User', backref=db.backref('news_articles', lazy='dynamic'))
    tags = db.relationship('Tag', secondary=news_tags, backref=db.backref('news_articles', lazy='dynamic'))

    def __repr__(self):
        return f'<NewsArticle {self.title}>'
        return f'<NewsArticle {self.title_en}>'
