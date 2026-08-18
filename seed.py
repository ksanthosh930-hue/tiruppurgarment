import os
from app import create_app, db
from app.models.user import User, Admin
from app.models.news import NewsCategory, NewsArticle, Tag
from app.models.knowledge import KnowledgeCategory, KnowledgeArticle
from app.models.company import CompanyCategory, Company
from app.models.job import Job
from app.models.service import Service
from app.models.tool import ToolCategory, Tool
from datetime import datetime, timedelta

def seed_data():
    app = create_app()
    with app.app_context():
        print("Starting seeding process...")
        
        # 1. Create a default admin/user from environment variables
        admin_email = os.environ.get('ADMIN_EMAIL')
        admin_password = os.environ.get('ADMIN_PASSWORD')
        if not admin_email or not admin_password:
            raise ValueError("ADMIN_EMAIL and ADMIN_PASSWORD environment variables must be configured in .env for database seeding.")
            
        user = User.query.filter_by(email=admin_email).first()
        if not user:
            user = User(username='admin', email=admin_email)
            user.set_password(admin_password)
            db.session.add(user)
            db.session.flush() # gets user.id
            
            admin = Admin(user_id=user.id, role='admin')
            db.session.add(admin)
            print("Default admin created from environment variables.")
        else:
            print("Admin user already exists.")
            
        # 2. Seed Tags
        tags_list = ['production', 'merchandising', 'textiles', 'knitwear', 'export', 'costing', 'fabric']
        tags_dict = {}
        for tag_name in tags_list:
            tag = Tag.query.filter_by(name=tag_name).first()
            if not tag:
                tag = Tag(name=tag_name, slug=tag_name)
                db.session.add(tag)
                print(f"Tag '{tag_name}' created.")
            tags_dict[tag_name] = tag
        db.session.flush()
        
        # 3. Seed Tool Categories & Tools
        # Category: Production / IE
        ie_cat = ToolCategory.query.filter_by(slug='production-ie').first()
        if not ie_cat:
            ie_cat = ToolCategory(name='Production & Industrial Engineering', slug='production-ie', description='Calculators for efficiency, cycle times and factory throughput.')
            db.session.add(ie_cat)
            db.session.flush()
            
        # Category: Fabric / Consumption
        fab_cat = ToolCategory.query.filter_by(slug='fabric-consumption').first()
        if not fab_cat:
            fab_cat = ToolCategory(name='Fabric & Consumption', slug='fabric-consumption', description='Calculators for GSM, yarn count, fabric consumption and markers.')
            db.session.add(fab_cat)
            db.session.flush()
            
        # Add SAM Calculator
        if not Tool.query.filter_by(slug='sam-calculator').first():
            sam_tool = Tool(
                name='SAM Calculator',
                slug='sam-calculator',
                description='Calculate Standard Allowed Minutes (SAM) / Standard Minute Value (SMV) for sewing operations with customizable personal, fatigue and machine allowances.',
                category_id=ie_cat.id,
                status='published',
                seo_title='Standard Allowed Minutes (SAM) Calculator — Tirupur Garments',
                seo_description='Free industrial engineering SAM and SMV calculator for sewing line operations, featuring customizable delay and fatigue allowances.'
            )
            db.session.add(sam_tool)
            print("SAM Calculator seeded.")
            
        # Add Fabric GSM Calculator
        if not Tool.query.filter_by(slug='fabric-gsm-calculator').first():
            gsm_tool = Tool(
                name='Fabric GSM Calculator',
                slug='fabric-gsm-calculator',
                description='Calculate weight of knit or woven fabrics in Grams per Square Meter (GSM) using custom rectangular dimensions or standard circular cutters (100 cm²).',
                category_id=fab_cat.id,
                status='published',
                seo_title='Fabric GSM Weight Calculator — Tirupur Garments',
                seo_description='Determine fabric weight in Grams per Square Meter (GSM) for knit and woven structures using circular sample cutters.'
            )
            db.session.add(gsm_tool)
            print("Fabric GSM Calculator seeded.")

        # Category: Costing & Planning
        cost_cat = ToolCategory.query.filter_by(slug='costing-planning').first()
        if not cost_cat:
            cost_cat = ToolCategory(name='Costing & Planning', slug='costing-planning', description='Calculators for fabric costing, CM cost calculations and margins.')
            db.session.add(cost_cat)
            db.session.flush()

        # Add Thread Consumption Calculator
        if not Tool.query.filter_by(slug='thread-consumption-calculator').first():
            thread_tool = Tool(
                name='Thread Consumption Calculator',
                slug='thread-consumption-calculator',
                description='Estimate total thread requirement per garment based on stitch classes (Lockstitch, Chainstitch, Overlock) and wastage factor.',
                category_id=fab_cat.id,
                status='published',
                seo_title='Thread Consumption Calculator for Apparel — Tirupur Garments',
                seo_description='Free garment thread consumption calculator. Estimate lockstitch, chainstitch, or overlock thread length with customizable SPI and waste factors.'
            )
            db.session.add(thread_tool)
            print("Thread Consumption Calculator seeded.")

        # Add Fabric Consumption Calculator
        if not Tool.query.filter_by(slug='fabric-consumption-calculator').first():
            fabric_tool = Tool(
                name='Fabric Consumption Calculator',
                slug='fabric-consumption-calculator',
                description='Calculate total weight of fabric required per piece or per dozen for standard knitted T-shirts and Polo models.',
                category_id=fab_cat.id,
                status='published',
                seo_title='Fabric Consumption Weight Calculator — Tirupur Garments',
                seo_description='Knit fabric consumption calculator. Estimate required fabric weight in grams per piece or kilograms per dozen using chest flat dimensions and GSM.'
            )
            db.session.add(fabric_tool)
            print("Fabric Consumption Calculator seeded.")

        # Add Garment Costing Calculator
        if not Tool.query.filter_by(slug='garment-costing-calculator').first():
            costing_tool = Tool(
                name='Garment Costing Calculator',
                slug='garment-costing-calculator',
                description='Sum raw fabric, trims, accessories, Cut & Make (CM), and logistics overheads to compute target FOB export prices.',
                category_id=cost_cat.id,
                status='published',
                seo_title='Garment FOB Costing Sheet Calculator — Tirupur Garments',
                seo_description='Industrial garment FOB costing sheet. Calculate piece costs by summarizing fabrics, CM, trims, packing, logistics, and profit margins.'
            )
            db.session.add(costing_tool)
            print("Garment Costing Calculator seeded.")

        # Add Fabric Cost Calculator
        if not Tool.query.filter_by(slug='fabric-cost-calculator').first():
            fabcost_tool = Tool(
                name='Fabric Cost Calculator',
                slug='fabric-cost-calculator',
                description='Estimate finished knitted fabric cost per kg based on raw yarn rates, knitting charges, dyeing costs, and processing losses.',
                category_id=cost_cat.id,
                status='published',
                seo_title='Finished Knitted Fabric Cost per kg Calculator — Tirupur Garments',
                seo_description='Calculate finished fabric cost per kg by factoring in yarn rates, knitting costs, dyeing/finishing rates, and manufacturing wastage.'
            )
            db.session.add(fabcost_tool)
            print("Fabric Cost Calculator seeded.")

        # Add CM Calculator
        if not Tool.query.filter_by(slug='cm-calculator').first():
            cm_tool = Tool(
                name='CM Calculator',
                slug='cm-calculator',
                description='Compute Cut and Make (CM) cost per garment considering operator wages, line overheads, expected efficiency, and target output.',
                category_id=cost_cat.id,
                status='published',
                seo_title='Garment Cut and Make (CM) Cost Calculator — Tirupur Garments',
                seo_description='Calculate CM (Cut and Make) cost per piece for sewing lines by factoring in operator wages, daily targets, line efficiency, and overheads.'
            )
            db.session.add(cm_tool)
            print("CM Calculator seeded.")
            
        # 4. Seed News Categories & News
        news_cat = NewsCategory.query.filter_by(slug='industry-news').first()
        if not news_cat:
            news_cat = NewsCategory(name='Industry News', slug='industry-news', description='Latest market reports, export indexes, and updates from the Tirupur garment cluster.')
            db.session.add(news_cat)
            db.session.flush()
            
        if not NewsArticle.query.filter_by(slug='tirupur-garment-export-growth-2026').first():
            art = NewsArticle(
                title='Tirupur Garment Export Growth Registers Double Digits in 2026',
                slug='tirupur-garment-export-growth-2026',
                summary='The Tirupur knitwear exporting hub has registered a 12% year-on-year growth in export earnings for the first quarter of 2026, driven by retail resurgence.',
                content='Tirupur, the knitwear capital of India, has registered a remarkable 12% export growth in Q1 2026. The resurgence of orders from European and North American retail brands has given manufacturers a solid order book.\n\nLocal exporters attribute this expansion to compliance audits, sustainable product sourcing, and investments in automated sewing technology. The local Tirupur Exporters Association (TEA) stated that the focus on high-value eco-friendly activewear and organic cotton jerseys has opened up new market channels in Scandinavian countries.',
                category_id=news_cat.id,
                author_id=user.id,
                status='published',
                published_at=datetime.utcnow() - timedelta(days=2),
                seo_title='Tirupur Garment Export Q1 Growth 2026 — Industry Reports',
                seo_description='Tirupur garment exporting hub registers a strong 12% growth in Q1 2026, boosting local knits production and mill capacities.'
            )
            art.tags.append(tags_dict['export'])
            art.tags.append(tags_dict['knitwear'])
            db.session.add(art)
            print("News article seeded.")
            
        # 5. Seed Knowledge Categories & Articles
        kn_cat = KnowledgeCategory.query.filter_by(slug='production-standards').first()
        if not kn_cat:
            kn_cat = KnowledgeCategory(name='Production Standards', slug='production-standards', description='Guides on industrial standards, quality checks and manufacturing procedures.')
            db.session.add(kn_cat)
            db.session.flush()
            
        if not KnowledgeArticle.query.filter_by(slug='understanding-sam-and-smv-in-sewing').first():
            k_art = KnowledgeArticle(
                title='Understanding SAM and SMV in Sewing Operations',
                slug='understanding-sam-and-smv-in-sewing',
                summary='A comprehensive technical guide to Standard Allowed Minutes (SAM) and Standard Minute Value (SMV) definitions, estimation formulas, and application in sewing lines.',
                content='In apparel manufacturing, Standard Allowed Minutes (SAM) and Standard Minute Value (SMV) are critical terms for measuring capacity and line balancing.\n\nSMV represents the basic time required to perform a specific sewing operation under standard conditions by a qualified operator. SAM, on the other hand, includes basic SMV plus necessary allowance variables (fatigue allowance, personal delay factor, machine delay allowances).\n\nIndustrial engineers in Tirupur utilize SAM values to calculate daily target output, set operator piece-rates, and design line schedules.',
                category_id=kn_cat.id,
                author_id=user.id,
                status='published',
                published_at=datetime.utcnow() - timedelta(days=5),
                seo_title='What is SAM and SMV in Garments Manufacturing — IE Guide',
                seo_description='Learn the technical definitions, differences, and calculations of Standard Allowed Minutes (SAM) in sewing operations.'
            )
            k_art.tags.append(tags_dict['production'])
            k_art.tags.append(tags_dict['fabric'])
            db.session.add(k_art)
            print("Knowledge article seeded.")
            
        # 6. Seed Company Categories & Companies
        comp_cat = CompanyCategory.query.filter_by(slug='exporters').first()
        if not comp_cat:
            comp_cat = CompanyCategory(name='Apparel Exporters', slug='exporters', description='Manufacturers and exporters of knitwear garments.')
            db.session.add(comp_cat)
            db.session.flush()
            
        comp = Company.query.filter_by(slug='tirupur-knits-exporters').first()
        if not comp:
            comp = Company(
                name='Tirupur Knits Exporters Ltd',
                slug='tirupur-knits-exporters',
                description='Tirupur Knits Exporters is a state-of-the-art apparel manufacturer specializing in 100% organic cotton T-shirts, Polo shirts, and hoodies. Established in 2012, we export premium knits to Europe and America.',
                address='Avinashi Road, Tirupur, Tamil Nadu, 641603',
                website='https://www.tirupurknitsexporters.com',
                email='info@tirupurknitsexporters.com',
                phone='+91-421-2234567',
                category_id=comp_cat.id,
                status='published',
                seo_title='Tirupur Knits Exporters — Organic Cotton Knitwear Manufacturer'
            )
            db.session.add(comp)
            db.session.flush()
            print("Company seeded.")
            
        # 7. Seed Services
        if not Service.query.filter_by(slug='rotary-fabric-printing').first():
            srv = Service(
                name='Rotary Fabric Printing Service',
                slug='rotary-fabric-printing',
                description='High-capacity rotary fabric printing supporting complex reactive, pigment, and discharge print patterns on knitwear panels. Handles up to 10 tons per day.',
                provider_id=comp.id,
                status='published'
            )
            db.session.add(srv)
            print("Service seeded.")
            
        # 8. Seed Jobs
        if not Job.query.filter_by(slug='production-manager-tirupur').first():
            job = Job(
                title='Production Manager - Sewing Division',
                slug='production-manager-tirupur',
                description='We are seeking an experienced Production Manager to oversee our knitwear sewing division. Candidate must have 8+ years experience in supervising floor lines, managing line efficiency, auditing SAM schedules, and ensuring international quality standards.',
                company_id=comp.id,
                location='Tirupur, TN',
                salary_range='₹6,00,000 - ₹9,00,000 P.A.',
                job_type='Full-time',
                status='published',
                seo_title='Production Manager Sewing Job in Tirupur Exporters'
            )
            db.session.add(job)
            print("Job seeded.")
            
        db.session.commit()
        print("Database seeding completed successfully!")

if __name__ == '__main__':
    seed_data()
