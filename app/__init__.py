from flask import Flask
from flask_bootstrap import Bootstrap5
from os import path, environ
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

def create_app():
    """Create and configure the Flask application"""
    app = Flask(__name__)
    
    # Configure the app
    app.config['SECRET_KEY'] = environ.get('SECRET_KEY', 'dev')
    app.config['PUBMED_API_KEY'] = environ.get('PUBMED_API_KEY')
    app.config['CONTACT_EMAIL'] = environ.get('CONTACT_EMAIL')
    
    # Initialize extensions
    bootstrap = Bootstrap5(app)
    
    # Ensure the config directory exists
    config_dir = path.join(app.root_path, 'config')
    if not path.exists(config_dir):
        os.makedirs(config_dir)
    
    # Register blueprints
    from .modules.routes import bp as main_bp
    from .modules.basic_search import bp as basic_search_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(basic_search_bp, url_prefix='/basic_search')
    
    return app 