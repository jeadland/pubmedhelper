from flask import Blueprint

bp = Blueprint('basic_search', __name__)

from app.modules.basic_search import routes 