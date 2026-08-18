from flask import Blueprint

# Create Blueprints
web_bp = Blueprint('web', __name__)
api_bp = Blueprint('api', __name__)
admin_bp = Blueprint('admin', __name__)

# Import routes to associate them with the blueprints
from app.routes import web, api, admin
