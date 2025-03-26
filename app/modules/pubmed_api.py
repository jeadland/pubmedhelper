import os
import json
import time
import requests
from typing import Dict, List, Optional
from datetime import datetime
from flask import current_app

class PubMedAPI:
    """Class to handle PubMed API interactions"""
    
    def __init__(self):
        self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        self.api_key = os.getenv("PUBMED_API_KEY")
        self.tool = "PubMedHelper"
        self.email = os.getenv("CONTACT_EMAIL")
        self.rate_limit = 0.1  # 10 requests per second max
        self.last_request_time = 0

    def _load_company_config(self) -> Dict:
        """Load company configuration from JSON file"""
        config_path = os.path.join(current_app.root_path, 'config', 'manufacturer_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                return json.load(f)
        return {}

    def _get_company_names(self, company: str, year: int) -> List[str]:
        """Get all applicable names for a company in a given year"""
        config = self._load_company_config()
        company_data = config.get(company, {})
        names = []

        # Add base company name variations
        for variation in company_data.get('variations', []):
            if variation['start_year'] <= year <= variation['end_year']:
                names.append(variation['name'])

        # Add names from acquisitions
        for acquisition in company_data.get('acquisitions', []):
            if acquisition['year'] <= year:
                names.append(acquisition['name'])

        # If no names found, use the company name itself
        return names if names else [company]

    def _respect_rate_limit(self):
        """Ensure we don't exceed API rate limits"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.rate_limit:
            time.sleep(self.rate_limit - time_since_last)
        self.last_request_time = time.time()

    def _make_request(self, endpoint: str, params: Dict) -> requests.Response:
        """Make a request to the PubMed API with rate limiting"""
        self._respect_rate_limit()
        base_params = {
            "api_key": self.api_key,
            "tool": self.tool,
            "email": self.email
        }
        params.update(base_params)
        response = requests.get(f"{self.base_url}{endpoint}", params=params)
        response.raise_for_status()
        return response

    def get_publication_count(self, query: str, year: int, company: str = None) -> int:
        """Get the count of publications for a specific query and year"""
        date_range = f"{year}/01/01[dp]:{year}/12/31[dp]"
        
        if company:
            company_names = self._get_company_names(company, year)
            company_terms = []
            for name in company_names:
                company_terms.extend([
                    f'"{name}"[Affiliation]',
                    f'"{name}"[Grant Number]',
                    f'"{name}"[Grant]'
                ])
            company_query = " OR ".join(company_terms)
            if query.strip():
                full_query = f"({query}) AND ({company_query}) AND {date_range}"
            else:
                full_query = f"({company_query}) AND {date_range}"
        else:
            if query.strip():
                full_query = f"({query}) AND {date_range}"
            else:
                full_query = date_range
        
        params = {
            "db": "pubmed",
            "term": full_query,
            "rettype": "count",
            "retmode": "json"
        }
        
        try:
            response = self._make_request("esearch.fcgi", params)
            data = response.json()
            return int(data["esearchresult"]["count"])
        except Exception as e:
            print(f"Error getting count for {query} in {year}: {str(e)}")
            return 0

    def get_publication_counts_by_year(self, topic: str, manufacturers: List[str], 
                                     start_year: int, end_year: int) -> Dict:
        """Get publication counts for each manufacturer by year"""
        config = self._load_company_config()
        
        # Sort manufacturers by display order
        sorted_manufacturers = sorted(
            manufacturers,
            key=lambda m: config.get(m, {}).get('display_order', float('inf'))
        )
        
        results = {
            "years": list(range(start_year, end_year + 1)),
            "manufacturers": sorted_manufacturers,
            "counts": {},
            "totals_by_year": {},
            "totals_by_manufacturer": {}
        }

        # Initialize counts dictionary
        for year in results["years"]:
            results["counts"][year] = {}
            results["totals_by_year"][year] = 0
            
            for manufacturer in sorted_manufacturers:
                count = self.get_publication_count(topic, year, manufacturer)
                results["counts"][year][manufacturer] = count
                results["totals_by_year"][year] += count
                
                # Update manufacturer totals
                if manufacturer not in results["totals_by_manufacturer"]:
                    results["totals_by_manufacturer"][manufacturer] = 0
                results["totals_by_manufacturer"][manufacturer] += count

        return results

    def get_detailed_results(self, topic: str, manufacturer: str, year: int, 
                           page: int = 1, results_per_page: int = 100) -> Dict:
        """Get detailed publication results for a specific query"""
        company_names = self._get_company_names(manufacturer, year)
        company_terms = []
        for name in company_names:
            company_terms.extend([
                f'"{name}"[Affiliation]',
                f'"{name}"[Grant Number]',
                f'"{name}"[Grant]'
            ])
        company_query = " OR ".join(company_terms)
        date_range = f"{year}/01/01[dp]:{year}/12/31[dp]"
        query = f"({topic}) AND ({company_query}) AND {date_range}"
        
        # First get PMIDs
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmax": results_per_page,
            "retstart": (page - 1) * results_per_page,
            "retmode": "json"
        }
        
        try:
            search_response = self._make_request("esearch.fcgi", search_params)
            search_data = search_response.json()
            pmids = search_data["esearchresult"]["idlist"]
            
            if not pmids:
                return {"count": 0, "results": []}
            
            # Then get details for these PMIDs
            fetch_params = {
                "db": "pubmed",
                "id": ",".join(pmids),
                "retmode": "json"
            }
            
            fetch_response = self._make_request("esummary.fcgi", fetch_params)
            fetch_data = fetch_response.json()
            
            results = []
            for pmid in pmids:
                article_data = fetch_data["result"][pmid]
                results.append({
                    "pmid": pmid,
                    "title": article_data.get("title", ""),
                    "authors": [author["name"] for author in article_data.get("authors", [])],
                    "journal": article_data.get("source", ""),
                    "pubdate": article_data.get("pubdate", ""),
                    "doi": article_data.get("doi", "")
                })
            
            return {
                "count": int(search_data["esearchresult"]["count"]),
                "results": results
            }
            
        except Exception as e:
            print(f"Error getting detailed results: {str(e)}")
            return {"count": 0, "results": []} 