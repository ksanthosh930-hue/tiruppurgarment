import os
import secrets
import uuid
from functools import wraps
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from flask import render_template, request, session, redirect, url_for, flash, abort, current_app
from app.routes import admin_bp
from app import db
from app.models.user import User, Admin
from app.models.news import NewsArticle, NewsCategory, Tag
from app.models.knowledge import KnowledgeArticle, KnowledgeCategory
from app.models.job import Job
from app.models.company import Company, CompanyCategory
from app.models.service import Service
from app.models.tool import Tool, ToolCategory
from app.models.contact import ContactMessage
from app.models.media import Media

# Helper decorator for protecting admin routes
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id') or not session.get('is_admin'):
            flash('Please log in as an administrator to access the admin panel.', 'error')
            return redirect(url_for('admin.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# Helper function to check CSRF token on POST requests
def check_csrf():
    token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not token or token != session.get('csrf_token'):
        abort(400, description="Invalid or missing CSRF token.")

# Image Byte Signature Verification Helper
def validate_image_signature(file_stream):
    header = file_stream.read(12)
    file_stream.seek(0)
    
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png', '.png'
    elif header.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg', '.jpg'
    elif header.startswith(b'GIF87a') or header.startswith(b'GIF89a'):
        return 'image/gif', '.gif'
    elif header.startswith(b'RIFF') and header[8:12] == b'WEBP':
        return 'image/webp', '.webp'
    return None, None

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id') and session.get('is_admin'):
        return redirect(url_for('admin.index'))
        
    next_url = request.args.get('next')
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            admin = Admin.query.filter_by(user_id=user.id).first()
            if admin:
                session.clear()
                session['user_id'] = user.id
                session['is_admin'] = True
                session['username'] = user.username
                session['csrf_token'] = secrets.token_hex(32)
                session.permanent = True
                
                flash('Successfully logged in as administrator.', 'success')
                return redirect(next_url or url_for('admin.index'))
                
        flash('Invalid email or password.', 'error')
        
    return render_template('admin/login.html', next=next_url)

@admin_bp.route('/logout')
def logout():
    session.clear()
    flash('Successfully logged out.', 'success')
    return redirect(url_for('admin.login'))

@admin_bp.route('/')
@admin_required
def index():
    news_count = NewsArticle.query.count()
    knowledge_count = KnowledgeArticle.query.count()
    jobs_count = Job.query.count()
    companies_count = Company.query.count()
    tools_count = Tool.query.count()
    messages = ContactMessage.query.order_by(ContactMessage.created_at.desc()).limit(5).all()
    
    return render_template(
        'admin/index.html',
        news_count=news_count,
        knowledge_count=knowledge_count,
        jobs_count=jobs_count,
        companies_count=companies_count,
        tools_count=tools_count,
        messages=messages
    )

# ----------------- NEWS ARTICLES CRUD -----------------

@admin_bp.route('/news')
@admin_required
def news_list():
    items = NewsArticle.query.order_by(NewsArticle.created_at.desc()).all()
    return render_template('admin/list.html', model_type='news', items=items)

@admin_bp.route('/news/new', methods=['GET', 'POST'])
@admin_required
def news_new():
    if request.method == 'POST':
        check_csrf()
        title = request.form.get('title')
        slug = request.form.get('slug') or title.lower().replace(' ', '-')
        # Clean slug
        slug = secure_filename(slug).lower()
        
        article = NewsArticle(
            title=title,
            slug=slug,
            summary=request.form.get('summary'),
            content=request.form.get('content'),
            category_id=request.form.get('category_id') or None,
            featured_image=request.form.get('featured_image'),
            status=request.form.get('status', 'draft'),
            seo_title=request.form.get('seo_title'),
            seo_description=request.form.get('seo_description'),
            canonical_url=request.form.get('canonical_url'),
            author_id=session.get('user_id'),
            published_at=datetime.utcnow() if request.form.get('status') == 'published' else None
        )
        
        db.session.add(article)
        db.session.commit()
        flash('News article created successfully.', 'success')
        return redirect(url_for('admin.news_list'))
        
    categories = NewsCategory.query.all()
    return render_template('admin/editor.html', model_type='news', item=None, categories=categories)

@admin_bp.route('/news/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def news_edit(id):
    item = NewsArticle.query.get_or_404(id)
    if request.method == 'POST':
        check_csrf()
        item.title = request.form.get('title')
        item.slug = secure_filename(request.form.get('slug') or item.title.lower().replace(' ', '-')).lower()
        item.summary = request.form.get('summary')
        item.content = request.form.get('content')
        item.category_id = request.form.get('category_id') or None
        item.featured_image = request.form.get('featured_image')
        item.status = request.form.get('status', 'draft')
        item.seo_title = request.form.get('seo_title')
        item.seo_description = request.form.get('seo_description')
        item.canonical_url = request.form.get('canonical_url')
        
        if item.status == 'published' and not item.published_at:
            item.published_at = datetime.utcnow()
            
        db.session.commit()
        flash('News article updated successfully.', 'success')
        return redirect(url_for('admin.news_list'))
        
    categories = NewsCategory.query.all()
    return render_template('admin/editor.html', model_type='news', item=item, categories=categories)

@admin_bp.route('/news/<int:id>/delete', methods=['POST'])
@admin_required
def news_delete(id):
    check_csrf()
    item = NewsArticle.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    flash('News article deleted successfully.', 'success')
    return redirect(url_for('admin.news_list'))

# ----------------- KNOWLEDGE ARTICLES CRUD -----------------

@admin_bp.route('/knowledge')
@admin_required
def knowledge_list():
    items = KnowledgeArticle.query.order_by(KnowledgeArticle.created_at.desc()).all()
    return render_template('admin/list.html', model_type='knowledge', items=items)

@admin_bp.route('/knowledge/new', methods=['GET', 'POST'])
@admin_required
def knowledge_new():
    if request.method == 'POST':
        check_csrf()
        title = request.form.get('title')
        slug = secure_filename(request.form.get('slug') or title.lower().replace(' ', '-')).lower()
        
        article = KnowledgeArticle(
            title=title,
            slug=slug,
            summary=request.form.get('summary'),
            content=request.form.get('content'),
            category_id=request.form.get('category_id') or None,
            featured_image=request.form.get('featured_image'),
            status=request.form.get('status', 'draft'),
            seo_title=request.form.get('seo_title'),
            seo_description=request.form.get('seo_description'),
            canonical_url=request.form.get('canonical_url'),
            author_id=session.get('user_id'),
            published_at=datetime.utcnow() if request.form.get('status') == 'published' else None
        )
        db.session.add(article)
        db.session.commit()
        flash('Knowledge article created successfully.', 'success')
        return redirect(url_for('admin.knowledge_list'))
        
    categories = KnowledgeCategory.query.all()
    return render_template('admin/editor.html', model_type='knowledge', item=None, categories=categories)

@admin_bp.route('/knowledge/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def knowledge_edit(id):
    item = KnowledgeArticle.query.get_or_404(id)
    if request.method == 'POST':
        check_csrf()
        item.title = request.form.get('title')
        item.slug = secure_filename(request.form.get('slug') or item.title.lower().replace(' ', '-')).lower()
        item.summary = request.form.get('summary')
        item.content = request.form.get('content')
        item.category_id = request.form.get('category_id') or None
        item.featured_image = request.form.get('featured_image')
        item.status = request.form.get('status', 'draft')
        item.seo_title = request.form.get('seo_title')
        item.seo_description = request.form.get('seo_description')
        item.canonical_url = request.form.get('canonical_url')
        
        if item.status == 'published' and not item.published_at:
            item.published_at = datetime.utcnow()
            
        db.session.commit()
        flash('Knowledge article updated successfully.', 'success')
        return redirect(url_for('admin.knowledge_list'))
        
    categories = KnowledgeCategory.query.all()
    return render_template('admin/editor.html', model_type='knowledge', item=item, categories=categories)

@admin_bp.route('/knowledge/<int:id>/delete', methods=['POST'])
@admin_required
def knowledge_delete(id):
    check_csrf()
    item = KnowledgeArticle.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    flash('Knowledge article deleted successfully.', 'success')
    return redirect(url_for('admin.knowledge_list'))

# ----------------- JOBS CRUD -----------------

@admin_bp.route('/jobs')
@admin_required
def jobs_list():
    items = Job.query.order_by(Job.created_at.desc()).all()
    return render_template('admin/list.html', model_type='jobs', items=items)

@admin_bp.route('/jobs/new', methods=['GET', 'POST'])
@admin_required
def jobs_new():
    if request.method == 'POST':
        check_csrf()
        title = request.form.get('title')
        slug = secure_filename(request.form.get('slug') or title.lower().replace(' ', '-')).lower()
        
        job = Job(
            title=title,
            slug=slug,
            description=request.form.get('description'),
            company_id=request.form.get('company_id'),
            location=request.form.get('location'),
            salary_range=request.form.get('salary_range'),
            job_type=request.form.get('job_type'),
            status=request.form.get('status', 'published'),
            seo_title=request.form.get('seo_title'),
            seo_description=request.form.get('seo_description')
        )
        db.session.add(job)
        db.session.commit()
        flash('Job vacancy posted successfully.', 'success')
        return redirect(url_for('admin.jobs_list'))
        
    companies = Company.query.all()
    return render_template('admin/editor.html', model_type='jobs', item=None, companies=companies)

@admin_bp.route('/jobs/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def jobs_edit(id):
    item = Job.query.get_or_404(id)
    if request.method == 'POST':
        check_csrf()
        item.title = request.form.get('title')
        item.slug = secure_filename(request.form.get('slug') or item.title.lower().replace(' ', '-')).lower()
        item.description = request.form.get('description')
        item.company_id = request.form.get('company_id')
        item.location = request.form.get('location')
        item.salary_range = request.form.get('salary_range')
        item.job_type = request.form.get('job_type')
        item.status = request.form.get('status', 'published')
        item.seo_title = request.form.get('seo_title')
        item.seo_description = request.form.get('seo_description')
        
        db.session.commit()
        flash('Job vacancy updated successfully.', 'success')
        return redirect(url_for('admin.jobs_list'))
        
    companies = Company.query.all()
    return render_template('admin/editor.html', model_type='jobs', item=item, companies=companies)

@admin_bp.route('/jobs/<int:id>/delete', methods=['POST'])
@admin_required
def jobs_delete(id):
    check_csrf()
    item = Job.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    flash('Job vacancy deleted successfully.', 'success')
    return redirect(url_for('admin.jobs_list'))

# ----------------- COMPANIES CRUD -----------------

@admin_bp.route('/companies')
@admin_required
def companies_list():
    items = Company.query.order_by(Company.created_at.desc()).all()
    return render_template('admin/list.html', model_type='companies', items=items)

@admin_bp.route('/companies/new', methods=['GET', 'POST'])
@admin_required
def companies_new():
    if request.method == 'POST':
        check_csrf()
        name = request.form.get('name')
        slug = secure_filename(request.form.get('slug') or name.lower().replace(' ', '-')).lower()
        
        company = Company(
            name=name,
            slug=slug,
            description=request.form.get('description'),
            category_id=request.form.get('category_id') or None,
            logo=request.form.get('logo'),
            website=request.form.get('website'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            address=request.form.get('address'),
            status=request.form.get('status', 'published'),
            seo_title=request.form.get('seo_title'),
            seo_description=request.form.get('seo_description')
        )
        db.session.add(company)
        db.session.commit()
        flash('Company directory profile created.', 'success')
        return redirect(url_for('admin.companies_list'))
        
    categories = CompanyCategory.query.all()
    return render_template('admin/editor.html', model_type='companies', item=None, categories=categories)

@admin_bp.route('/companies/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def companies_edit(id):
    item = Company.query.get_or_404(id)
    if request.method == 'POST':
        check_csrf()
        item.name = request.form.get('name')
        item.slug = secure_filename(request.form.get('slug') or item.name.lower().replace(' ', '-')).lower()
        item.description = request.form.get('description')
        item.category_id = request.form.get('category_id') or None
        item.logo = request.form.get('logo')
        item.website = request.form.get('website')
        item.email = request.form.get('email')
        item.phone = request.form.get('phone')
        item.address = request.form.get('address')
        item.status = request.form.get('status', 'published')
        item.seo_title = request.form.get('seo_title')
        item.seo_description = request.form.get('seo_description')
        
        db.session.commit()
        flash('Company directory profile updated.', 'success')
        return redirect(url_for('admin.companies_list'))
        
    categories = CompanyCategory.query.all()
    return render_template('admin/editor.html', model_type='companies', item=item, categories=categories)

@admin_bp.route('/companies/<int:id>/delete', methods=['POST'])
@admin_required
def companies_delete(id):
    check_csrf()
    item = Company.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    flash('Company profile deleted successfully.', 'success')
    return redirect(url_for('admin.companies_list'))

# ----------------- MEDIA MANAGEMENT -----------------

@admin_bp.route('/media')
@admin_required
def media_list():
    items = Media.query.order_by(Media.created_at.desc()).all()
    return render_template('admin/media.html', items=items)

@admin_bp.route('/media/upload', methods=['POST'])
@admin_required
def media_upload():
    check_csrf()
    if 'file' not in request.files:
        flash('No file partition provided in request.', 'error')
        return redirect(url_for('admin.media_list'))
        
    file = request.files['file']
    if file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('admin.media_list'))
        
    # Enforce size validation via content length or stream check
    # Check actual file size by checking read offset
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    
    if size > 5 * 1024 * 1024:
        flash('File size exceeds the 5MB maximum limit.', 'error')
        return redirect(url_for('admin.media_list'))
        
    # Validate signature and type
    mime_type, extension = validate_image_signature(file)
    if not mime_type or not extension:
        flash('Invalid file format. Only PNG, JPG, JPEG, GIF, and WEBP image files are allowed. SVG and other files are rejected.', 'error')
        return redirect(url_for('admin.media_list'))
        
    # Generate UUID based filename to prevent path traversal and disclosure
    safe_filename = f"{uuid.uuid4().hex}{extension}"
    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
    
    # Ensure uploads folder exists
    os.makedirs(upload_folder, exist_ok=True)
    
    filepath = os.path.join(upload_folder, safe_filename)
    file.save(filepath)
    
    # Save database entry
    media_url = f"/static/uploads/{safe_filename}"
    media_entry = Media(
        filename=file.filename,
        filepath=media_url,
        file_type=mime_type,
        file_size=size,
        uploaded_by_id=session.get('user_id')
    )
    db.session.add(media_entry)
    db.session.commit()
    
    flash(f'Image "{file.filename}" uploaded successfully as "{safe_filename}".', 'success')
    return redirect(url_for('admin.media_list'))
