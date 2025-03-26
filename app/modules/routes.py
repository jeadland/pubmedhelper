from flask import Blueprint, render_template, request, jsonify, send_file, current_app
import json
import csv
from io import StringIO
from datetime import datetime
import os
from .pubmed_api import PubMedAPI

bp = Blueprint('main', __name__)
pubmed_api = PubMedAPI()

def get_config_path():
    return os.path.join(current_app.root_path, 'config', 'manufacturer_config.json')

def load_company_config():
    config_path = get_config_path()
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return json.load(f)
    return {}

def save_company_config(config):
    config_path = get_config_path()
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

@bp.route('/')
def index():
    """Render the main search page"""
    companies = load_company_config()
    return render_template('index.html', companies=companies)

@bp.route('/config')
def config():
    """Render the company configuration page"""
    companies = load_company_config()
    return render_template('config.html', companies=companies)

@bp.route('/api/companies', methods=['GET'])
def get_companies():
    """Get all company configurations"""
    return jsonify(load_company_config())

@bp.route('/api/companies', methods=['POST'])
def create_company():
    """Create or update a company configuration"""
    try:
        data = request.get_json()
        company_name = data.get('name')
        if not company_name:
            return jsonify({"error": "Company name is required"}), 400

        config = load_company_config()
        
        # Create new company entry with display order
        company_data = {
            "display_order": data.get('display_order', len(config) + 1),
            "variations": []
        }

        # Add name variations
        variations = data.get('variations', [])
        for var in variations:
            if not all(k in var for k in ('name', 'start_year', 'end_year')):
                return jsonify({"error": "Invalid variation format"}), 400
            company_data["variations"].append({
                "name": var['name'],
                "start_year": int(var['start_year']),
                "end_year": int(var['end_year'])
            })

        # Add acquisitions
        acquisitions = data.get('acquisitions', [])
        company_data["acquisitions"] = []
        for acq in acquisitions:
            if not all(k in acq for k in ('name', 'year')):
                return jsonify({"error": "Invalid acquisition format"}), 400
            company_data["acquisitions"].append({
                "name": acq['name'],
                "year": int(acq['year'])
            })

        config[company_name] = company_data
        save_company_config(config)
        return jsonify({"message": "Company configuration saved", "company": company_data})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/api/companies/<company_name>', methods=['DELETE'])
def delete_company(company_name):
    """Delete a company configuration"""
    try:
        config = load_company_config()
        if company_name in config:
            del config[company_name]
            save_company_config(config)
            return jsonify({"message": "Company deleted"})
        return jsonify({"error": "Company not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/api/companies/reorder', methods=['POST'])
def reorder_companies():
    """Update the display order of companies"""
    try:
        data = request.get_json()
        order = data.get('order', [])
        
        config = load_company_config()
        for i, company_name in enumerate(order):
            if company_name in config:
                config[company_name]['display_order'] = i + 1
        
        save_company_config(config)
        return jsonify({"message": "Display order updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/search', methods=['POST'])
def search():
    """Handle the search request and return publication counts"""
    try:
        data = request.get_json()
        topic = data.get('topic', '')  # Make topic optional
        start_year = int(data.get('start_year'))
        end_year = int(data.get('end_year'))
        manufacturers = data.get('manufacturers', [])

        if not all([start_year, end_year, manufacturers]):  # Remove topic from required parameters
            return jsonify({"error": "Missing required parameters"}), 400

        results = pubmed_api.get_publication_counts_by_year(
            topic, manufacturers, start_year, end_year
        )
        
        return jsonify(results)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/details', methods=['GET'])
def get_details():
    """Get detailed results for a specific year and manufacturer"""
    try:
        topic = request.args.get('topic')
        manufacturer = request.args.get('manufacturer')
        year = int(request.args.get('year'))
        page = int(request.args.get('page', 1))
        
        if not all([topic, manufacturer, year]):
            return jsonify({"error": "Missing required parameters"}), 400
        
        results = pubmed_api.get_detailed_results(
            topic, manufacturer, year, page
        )
        
        return jsonify(results)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/export', methods=['POST'])
def export_results():
    """Export the results as a CSV file"""
    try:
        data = request.get_json()
        results = data.get('results')
        
        if not results:
            return jsonify({"error": "No results to export"}), 400
        
        # Create CSV in memory
        output = StringIO()
        writer = csv.writer(output)
        
        # Write headers
        headers = ['Year'] + results['manufacturers'] + ['Total']
        writer.writerow(headers)
        
        # Write data rows
        for year in results['years']:
            row = [year]
            for manufacturer in results['manufacturers']:
                row.append(results['counts'][str(year)][manufacturer])
            row.append(results['totals_by_year'][str(year)])
            writer.writerow(row)
        
        # Add totals row
        totals_row = ['Total']
        for manufacturer in results['manufacturers']:
            totals_row.append(results['totals_by_manufacturer'][manufacturer])
        total_sum = sum(results['totals_by_manufacturer'].values())
        totals_row.append(total_sum)
        writer.writerow(totals_row)
        
        # Prepare the response
        output.seek(0)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return send_file(
            output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'pubmed_results_{timestamp}.csv'
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500 