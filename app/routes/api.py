from flask import jsonify, request
from app.routes import api_bp
from app import db
from app.models.news import NewsArticle
from app.models.knowledge import KnowledgeArticle
from app.models.job import Job
from app.models.company import Company
from app.models.service import Service
from app.models.tool import Tool
from app.models.contact import ContactMessage

@api_bp.route('/news', methods=['GET'])
def get_news():
    articles = NewsArticle.query.filter_by(status='published').order_by(NewsArticle.published_at.desc()).all()
    return jsonify([{
        'id': a.id,
        'title': a.title,
        'slug': a.slug,
        'summary': a.summary,
        'content': a.content,
        'featured_image': a.featured_image,
        'published_at': a.published_at.isoformat() if a.published_at else None,
        'category': a.category.name if a.category else None,
        'seo_title': a.seo_title,
        'seo_description': a.seo_description
    } for a in articles])

@api_bp.route('/news/<slug>', methods=['GET'])
def get_news_detail(slug):
    a = NewsArticle.query.filter_by(slug=slug, status='published').first_or_404()
    return jsonify({
        'id': a.id,
        'title': a.title,
        'slug': a.slug,
        'summary': a.summary,
        'content': a.content,
        'featured_image': a.featured_image,
        'published_at': a.published_at.isoformat() if a.published_at else None,
        'category': a.category.name if a.category else None,
        'seo_title': a.seo_title,
        'seo_description': a.seo_description
    })

@api_bp.route('/knowledge', methods=['GET'])
def get_knowledge():
    articles = KnowledgeArticle.query.filter_by(status='published').order_by(KnowledgeArticle.published_at.desc()).all()
    return jsonify([{
        'id': a.id,
        'title': a.title,
        'slug': a.slug,
        'summary': a.summary,
        'content': a.content,
        'featured_image': a.featured_image,
        'published_at': a.published_at.isoformat() if a.published_at else None,
        'category': a.category.name if a.category else None,
        'seo_title': a.seo_title,
        'seo_description': a.seo_description
    } for a in articles])

@api_bp.route('/knowledge/<slug>', methods=['GET'])
def get_knowledge_detail(slug):
    a = KnowledgeArticle.query.filter_by(slug=slug, status='published').first_or_404()
    return jsonify({
        'id': a.id,
        'title': a.title,
        'slug': a.slug,
        'summary': a.summary,
        'content': a.content,
        'featured_image': a.featured_image,
        'published_at': a.published_at.isoformat() if a.published_at else None,
        'category': a.category.name if a.category else None,
        'seo_title': a.seo_title,
        'seo_description': a.seo_description
    })

@api_bp.route('/jobs', methods=['GET'])
def get_jobs():
    jobs = Job.query.filter_by(status='published').order_by(Job.created_at.desc()).all()
    return jsonify([{
        'id': j.id,
        'title': j.title,
        'slug': j.slug,
        'description': j.description,
        'location': j.location,
        'salary_range': j.salary_range,
        'job_type': j.job_type,
        'company': j.company.name if j.company else None,
        'created_at': j.created_at.isoformat()
    } for j in jobs])

@api_bp.route('/companies', methods=['GET'])
def get_companies():
    companies = Company.query.filter_by(status='published').all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'slug': c.slug,
        'description': c.description,
        'logo': c.logo,
        'category': c.category.name if c.category else None,
        'website': c.website,
        'email': c.email,
        'phone': c.phone,
        'address': c.address
    } for c in companies])

@api_bp.route('/services', methods=['GET'])
def get_services():
    services = Service.query.filter_by(status='published').all()
    return jsonify([{
        'id': s.id,
        'name': s.name,
        'slug': s.slug,
        'description': s.description,
        'provider': s.provider.name if s.provider else None
    } for s in services])

@api_bp.route('/tools', methods=['GET'])
def get_tools():
    tools = Tool.query.filter_by(status='published').all()
    return jsonify([{
        'id': t.id,
        'name': t.name,
        'slug': t.slug,
        'description': t.description,
        'category': t.category.name if t.category else None
    } for t in tools])

@api_bp.route('/tools/<slug>', methods=['GET'])
def get_tool_detail(slug):
    t = Tool.query.filter_by(slug=slug, status='published').first_or_404()
    return jsonify({
        'id': t.id,
        'name': t.name,
        'slug': t.slug,
        'description': t.description,
        'category': t.category.name if t.category else None
    })

@api_bp.route('/contact', methods=['POST'])
def create_contact():
    data = request.get_json() or request.form
    
    if not data or not data.get('name') or not data.get('email') or not data.get('subject') or not data.get('message'):
        return jsonify({'error': 'Missing required fields'}), 400
        
    msg = ContactMessage(
        name=data.get('name'),
        email=data.get('email'),
        subject=data.get('subject'),
        message=data.get('message')
    )
    
    db.session.add(msg)
    db.session.commit()
    
    return jsonify({'success': 'Message submitted successfully', 'id': msg.id}), 201
