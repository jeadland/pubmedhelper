# PubMed Publication Analysis Tool

A web application for analyzing publication trends across different manufacturers in PubMed. This tool allows users to search for publications by topic and visualize publication counts over time for different manufacturers, taking into account historical company name changes.

## Features

- Search PubMed by topic and date range
- Track publication counts for multiple manufacturers
- Handle historical company name changes (e.g., Siemens acquiring Varian)
- Interactive visualization of publication trends
- Detailed view of individual publications
- Export results to CSV for further analysis

## Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd PubMedHelper
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root with the following content:
```
PUBMED_API_KEY=your_api_key_here
CONTACT_EMAIL=your_email@example.com
SECRET_KEY=your_secret_key_here
```

Replace the placeholders with your actual values:
- Get a PubMed API key from: https://www.ncbi.nlm.nih.gov/account/settings/
- Use your contact email
- Generate a random secret key for Flask

## Running the Application

1. Make sure your virtual environment is activated:
```bash
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Start the development server:
```bash
python run.py
```

3. Open your web browser and navigate to:
```
http://localhost:5000
```

## Usage

1. Enter a search topic (e.g., "MRI" or "CT Scanner")
2. Select a date range
3. Choose which manufacturers to include in the analysis
4. Click "Search" to generate results
5. View the trend chart and data table
6. Click on individual counts to see detailed publication information
7. Export results to CSV for further analysis

## Manufacturer Configuration

The application includes a configuration file (`app/config/manufacturer_config.json`) that maps manufacturer names to their historical variations. This ensures accurate tracking of publications when companies undergo name changes or acquisitions.

Current mappings include:
- Siemens (including Varian before 2021)
- Canon (including Toshiba before 2017)
- GE (General Electric)
- Philips

## Development

The application is built with:
- Flask (Python web framework)
- Bootstrap 5 (Frontend framework)
- Chart.js (Interactive charts)
- PubMed E-utilities API

Key files:
- `app/modules/pubmed_api.py`: PubMed API interaction
- `app/modules/routes.py`: Web routes and request handling
- `app/templates/index.html`: Main web interface
- `app/config/manufacturer_config.json`: Manufacturer name mappings

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 