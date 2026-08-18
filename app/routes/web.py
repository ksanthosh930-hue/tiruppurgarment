from flask import render_template, abort, make_response, request
from app import db
from app.routes import web_bp
from app.models.news import NewsArticle, NewsCategory
from app.models.knowledge import KnowledgeArticle, KnowledgeCategory
from app.models.job import Job
from app.models.company import Company, CompanyCategory
from app.models.service import Service
from app.models.tool import Tool, ToolCategory
from datetime import datetime

@web_bp.route('/')
def index():
    # Fetch recent published items for homepage
    recent_news = NewsArticle.query.filter_by(status='published').order_by(NewsArticle.published_at.desc()).limit(3).all()
    popular_tools = Tool.query.filter_by(status='published').limit(4).all()
    recent_jobs = Job.query.filter_by(status='published').order_by(Job.created_at.desc()).limit(3).all()
    featured_companies = Company.query.filter_by(status='published').limit(4).all()
    recent_knowledge = KnowledgeArticle.query.filter_by(status='published').order_by(KnowledgeArticle.published_at.desc()).limit(3).all()
    
    return render_template(
        'index.html',
        recent_news=recent_news,
        popular_tools=popular_tools,
        recent_jobs=recent_jobs,
        featured_companies=featured_companies,
        recent_knowledge=recent_knowledge
    )

@web_bp.route('/news')
def news_list():
    page = request.args.get('page', 1, type=int)
    pagination = NewsArticle.query.filter_by(status='published').order_by(NewsArticle.published_at.desc()).paginate(page=page, per_page=10, error_out=False)
    articles = pagination.items
    categories = NewsCategory.query.all()
    return render_template('news.html', articles=articles, categories=categories, pagination=pagination, article=None)

@web_bp.route('/news/category/<slug>')
def news_category_list(slug):
    category = NewsCategory.query.filter_by(slug=slug).first_or_404()
    page = request.args.get('page', 1, type=int)
    pagination = NewsArticle.query.filter_by(status='published', category_id=category.id).order_by(NewsArticle.published_at.desc()).paginate(page=page, per_page=10, error_out=False)
    articles = pagination.items
    categories = NewsCategory.query.all()
    return render_template('news.html', articles=articles, categories=categories, pagination=pagination, category=category, article=None)

@web_bp.route('/news/<slug>')
def news_detail(slug):
    article = NewsArticle.query.filter_by(slug=slug, status='published').first_or_404()
    related_news = NewsArticle.query.filter(
        NewsArticle.category_id == article.category_id,
        NewsArticle.id != article.id,
        NewsArticle.status == 'published'
    ).limit(3).all()
    return render_template('news.html', article=article, related_news=related_news)

@web_bp.route('/knowledge')
def knowledge_list():
    page = request.args.get('page', 1, type=int)
    pagination = KnowledgeArticle.query.filter_by(status='published').order_by(KnowledgeArticle.published_at.desc()).paginate(page=page, per_page=10, error_out=False)
    articles = pagination.items
    categories = KnowledgeCategory.query.all()
    return render_template('knowledge.html', articles=articles, categories=categories, pagination=pagination, article=None)

@web_bp.route('/knowledge/category/<slug>')
def knowledge_category_list(slug):
    category = KnowledgeCategory.query.filter_by(slug=slug).first_or_404()
    page = request.args.get('page', 1, type=int)
    pagination = KnowledgeArticle.query.filter_by(status='published', category_id=category.id).order_by(KnowledgeArticle.published_at.desc()).paginate(page=page, per_page=10, error_out=False)
    articles = pagination.items
    categories = KnowledgeCategory.query.all()
    return render_template('knowledge.html', articles=articles, categories=categories, pagination=pagination, category=category, article=None)

@web_bp.route('/knowledge/<slug>')
def knowledge_detail(slug):
    article = KnowledgeArticle.query.filter_by(slug=slug, status='published').first_or_404()
    related_articles = KnowledgeArticle.query.filter(
        KnowledgeArticle.category_id == article.category_id,
        KnowledgeArticle.id != article.id,
        KnowledgeArticle.status == 'published'
    ).limit(3).all()
    return render_template('knowledge.html', article=article, related_articles=related_articles)

@web_bp.route('/jobs')
def jobs_list():
    page = request.args.get('page', 1, type=int)
    pagination = Job.query.filter_by(status='published').order_by(Job.created_at.desc()).paginate(page=page, per_page=10, error_out=False)
    jobs = pagination.items
    return render_template('jobs.html', jobs=jobs, pagination=pagination, job=None)

@web_bp.route('/jobs/<slug>')
def job_detail(slug):
    job = Job.query.filter_by(slug=slug, status='published').first_or_404()
    related_jobs = Job.query.filter(
        Job.company_id == job.company_id,
        Job.id != job.id,
        Job.status == 'published'
    ).limit(3).all()
    return render_template('jobs.html', job=job, related_jobs=related_jobs)

@web_bp.route('/companies')
def companies_list():
    page = request.args.get('page', 1, type=int)
    pagination = Company.query.filter_by(status='published').order_by(Company.created_at.desc()).paginate(page=page, per_page=10, error_out=False)
    companies = pagination.items
    categories = CompanyCategory.query.all()
    return render_template('companies.html', companies=companies, categories=categories, pagination=pagination, company=None)

@web_bp.route('/companies/<slug>')
def company_detail(slug):
    company = Company.query.filter_by(slug=slug, status='published').first_or_404()
    company_jobs = Job.query.filter_by(company_id=company.id, status='published').all()
    company_services = Service.query.filter_by(provider_id=company.id, status='published').all()
    return render_template('companies.html', company=company, company_jobs=company_jobs, company_services=company_services)

@web_bp.route('/services')
def services_list():
    services = Service.query.filter_by(status='published').all()
    return render_template('services.html', services=services, service=None)

@web_bp.route('/services/<slug>')
def service_detail(slug):
    service = Service.query.filter_by(slug=slug, status='published').first_or_404()
    return render_template('services.html', service=service)

@web_bp.route('/tools')
def tools_list():
    categories = ToolCategory.query.all()
    tools = Tool.query.filter_by(status='published').all()
    return render_template('tools.html', categories=categories, tools=tools)

@web_bp.route('/tools/category/<slug>')
def tools_category_list(slug):
    category = ToolCategory.query.filter_by(slug=slug).first_or_404()
    tools = Tool.query.filter_by(status='published', category_id=category.id).all()
    categories = ToolCategory.query.all()
    return render_template('tools.html', categories=categories, tools=tools, active_category=category)

@web_bp.route('/search')
def search():
    query = request.args.get('q', '').strip()
    results = {
        'news': [],
        'knowledge': [],
        'jobs': [],
        'companies': [],
        'tools': []
    }
    
    if query:
        results['news'] = NewsArticle.query.filter(
            NewsArticle.status == 'published',
            db.or_(
                NewsArticle.title.ilike(f'%{query}%'),
                NewsArticle.summary.ilike(f'%{query}%'),
                NewsArticle.content.ilike(f'%{query}%')
            )
        ).limit(10).all()
        
        results['knowledge'] = KnowledgeArticle.query.filter(
            KnowledgeArticle.status == 'published',
            db.or_(
                KnowledgeArticle.title.ilike(f'%{query}%'),
                KnowledgeArticle.summary.ilike(f'%{query}%'),
                KnowledgeArticle.content.ilike(f'%{query}%')
            )
        ).limit(10).all()
        
        results['jobs'] = Job.query.filter(
            Job.status == 'published',
            db.or_(
                Job.title.ilike(f'%{query}%'),
                Job.description.ilike(f'%{query}%'),
                Job.location.ilike(f'%{query}%')
            )
        ).limit(10).all()
        
        results['companies'] = Company.query.filter(
            Company.status == 'published',
            db.or_(
                Company.name.ilike(f'%{query}%'),
                Company.description.ilike(f'%{query}%'),
                Company.address.ilike(f'%{query}%')
            )
        ).limit(10).all()
        
        results['tools'] = Tool.query.filter(
            Tool.status == 'published',
            db.or_(
                Tool.name.ilike(f'%{query}%'),
                Tool.description.ilike(f'%{query}%')
            )
        ).limit(10).all()
        
    return render_template('search.html', query=query, results=results)

@web_bp.route('/tools/<slug>')
def tool_detail(slug):
    tool = Tool.query.filter_by(slug=slug, status='published').first_or_404()
    
    # Fetch related tools in the same category
    related_tools = Tool.query.filter(
        Tool.category_id == tool.category_id,
        Tool.id != tool.id,
        Tool.status == 'published'
    ).limit(3).all()
    
    # Fetch related knowledge articles about this category
    related_knowledge = KnowledgeArticle.query.filter_by(status='published').limit(2).all()
    
    return render_template('tool_detail.html', tool=tool, related_tools=related_tools, related_knowledge=related_knowledge)

@web_bp.route('/ai-studio')
def ai_studio():
    return render_template('ai_studio.html')

@web_bp.route('/sitemap.xml')
def sitemap():
    base_url = request.url_root.rstrip('/')
    pages = []
    
    # Static pages
    pages.append({'loc': f"{base_url}/", 'changefreq': 'daily', 'priority': '1.0'})
    pages.append({'loc': f"{base_url}/news", 'changefreq': 'daily', 'priority': '0.9'})
    pages.append({'loc': f"{base_url}/knowledge", 'changefreq': 'weekly', 'priority': '0.8'})
    pages.append({'loc': f"{base_url}/jobs", 'changefreq': 'daily', 'priority': '0.8'})
    pages.append({'loc': f"{base_url}/companies", 'changefreq': 'weekly', 'priority': '0.7'})
    pages.append({'loc': f"{base_url}/services", 'changefreq': 'weekly', 'priority': '0.6'})
    pages.append({'loc': f"{base_url}/tools", 'changefreq': 'monthly', 'priority': '0.9'})
    pages.append({'loc': f"{base_url}/ai-studio", 'changefreq': 'monthly', 'priority': '0.7'})
    
    # Dynamic content URLs
    news_articles = NewsArticle.query.filter_by(status='published').all()
    for art in news_articles:
        pages.append({'loc': f"{base_url}/news/{art.slug}", 'changefreq': 'weekly', 'priority': '0.8'})
        
    knowledge_articles = KnowledgeArticle.query.filter_by(status='published').all()
    for art in knowledge_articles:
        pages.append({'loc': f"{base_url}/knowledge/{art.slug}", 'changefreq': 'monthly', 'priority': '0.7'})
        
    jobs = Job.query.filter_by(status='published').all()
    for job in jobs:
        pages.append({'loc': f"{base_url}/jobs/{job.slug}", 'changefreq': 'weekly', 'priority': '0.7'})
        
    companies = Company.query.filter_by(status='published').all()
    for comp in companies:
        pages.append({'loc': f"{base_url}/companies/{comp.slug}", 'changefreq': 'weekly', 'priority': '0.6'})
        
    tools = Tool.query.filter_by(status='published').all()
    for t in tools:
        pages.append({'loc': f"{base_url}/tools/{t.slug}", 'changefreq': 'monthly', 'priority': '0.8'})

    # Dynamic Category URLs
    news_cats = NewsCategory.query.all()
    for cat in news_cats:
        pages.append({'loc': f"{base_url}/news/category/{cat.slug}", 'changefreq': 'weekly', 'priority': '0.7'})
    
    kn_cats = KnowledgeCategory.query.all()
    for cat in kn_cats:
        pages.append({'loc': f"{base_url}/knowledge/category/{cat.slug}", 'changefreq': 'weekly', 'priority': '0.6'})
        
    tool_cats = ToolCategory.query.all()
    for cat in tool_cats:
        pages.append({'loc': f"{base_url}/tools/category/{cat.slug}", 'changefreq': 'weekly', 'priority': '0.7'})
        
    sitemap_xml = render_template('sitemap_xml.html', pages=pages)
    response = make_response(sitemap_xml)
    response.headers['Content-Type'] = 'application/xml'
    return response

@web_bp.route('/robots.txt')
def robots():
    base_url = request.url_root.rstrip('/')
    robots_txt = f"User-agent: *\nDisallow: /admin/\nDisallow: /api/\nSitemap: {base_url}/sitemap.xml\n"
    response = make_response(robots_txt)
    response.headers['Content-Type'] = 'text/plain'
    return response
