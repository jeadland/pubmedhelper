import os
import json
import time
import requests
import logging
from typing import Dict, List, Optional
from datetime import datetime
from flask import current_app

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PubMedAPI:
    """Class to handle PubMed API interactions"""
    
    def __init__(self):
        self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        self.api_key = os.getenv("PUBMED_API_KEY")
        self.tool = "PubMedHelper"
        self.email = os.getenv("CONTACT_EMAIL")
        self.rate_limit = 0.34  # ~3 requests per second max
        self.last_request_time = 0
        self.progress_callback = None
        self.verification_delay = 2.0  # Additional delay for verification
        self.max_retries = 5  # Increased from 3 to 5
        self.base_retry_delay = 1.0

    def set_progress_callback(self, callback):
        """Set callback function for progress updates"""
        self.progress_callback = callback

    def _update_progress(self, current, total, status=""):
        """Update progress through callback if set"""
        if self.progress_callback:
            self.progress_callback(current, total, status)

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
        """Ensure we don't exceed API rate limits with logging"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.rate_limit:
            sleep_time = self.rate_limit - time_since_last
            logger.info(f"Rate limiting: Sleeping for {sleep_time:.2f} seconds")
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def _verify_response(self, response: requests.Response, params: Dict) -> bool:
        """Verify response is valid and complete"""
        try:
            data = response.json()
            if "esearchresult" in data:
                count = int(data["esearchresult"].get("count", 0))
                # If count is suspiciously low, add extra verification delay
                if count == 0:
                    logger.warning(f"Zero results found for query. Adding verification delay.")
                    time.sleep(self.verification_delay)
                    # Retry the request once more
                    self._respect_rate_limit()
                    verify_response = requests.get(f"{self.base_url}esearch.fcgi", params=params)
                    verify_data = verify_response.json()
                    verify_count = int(verify_data["esearchresult"].get("count", 0))
                    if verify_count != count:
                        logger.warning(f"Count mismatch: {count} vs {verify_count}. Using higher value.")
                        return False
            return True
        except Exception as e:
            logger.error(f"Verification failed: {str(e)}")
            return False

    def _make_request(self, endpoint: str, params: Dict) -> requests.Response:
        """Make a request to the PubMed API with enhanced rate limiting and verification"""
        base_params = {
            "api_key": self.api_key,
            "tool": self.tool,
            "email": self.email,
            "usehistory": "y"
        }
        params.update(base_params)
        
        retry_delay = self.base_retry_delay
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                self._respect_rate_limit()
                logger.info(f"Making request attempt {attempt + 1}/{self.max_retries}")
                response = requests.get(f"{self.base_url}{endpoint}", params=params)
                response.raise_for_status()
                
                # Verify response
                if self._verify_response(response, params):
                    return response
                
                # If verification failed, retry with longer delay
                logger.warning(f"Response verification failed on attempt {attempt + 1}")
                time.sleep(retry_delay)
                retry_delay *= 2
                
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.error(f"Request failed on attempt {attempt + 1}: {str(e)}")
                if attempt < self.max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    
        raise last_error or Exception("All retry attempts failed")

    def get_publication_count(self, query: str, year: int, company: str = None) -> int:
        """Get the count of publications with enhanced verification"""
        date_range = f"{year}/01/01[dp]:{year}/12/31[dp]"
        
        if company:
            company_names = self._get_company_names(company, year)
            company_terms = []
            
            # Add base company terms without quotes for more flexible matching
            for name in company_names:
                # Add the full name variations
                company_terms.extend([
                    f"({name}[Affiliation])",
                    f"({name}[Grant Number])",
                    f"({name}[Grant])"
                ])
                
                # Add abbreviated versions for certain companies
                if name.startswith("General Electric"):
                    company_terms.extend([
                        "(GE[Affiliation])",
                        "(GE[Grant Number])",
                        "(GE[Grant])"
                    ])
                elif name.startswith("GE HealthCare"):
                    company_terms.extend([
                        "(GE Healthcare[Affiliation])",
                        "(GE Healthcare[Grant Number])",
                        "(GE Healthcare[Grant])"
                    ])
            
            # Remove duplicates while preserving order
            company_terms = list(dict.fromkeys(company_terms))
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
        
        logger.info(f"Executing query: {full_query}")
        
        params = {
            "db": "pubmed",
            "term": full_query,
            "rettype": "count",
            "retmode": "json"
        }
        
        try:
            # Make initial request
            response = self._make_request("esearch.fcgi", params)
            data = response.json()
            count = int(data["esearchresult"]["count"])
            
            # For higher counts, we trust the result more
            if count >= 100:
                logger.info(f"Final count for query: {count}")
                return count
                
            # For lower counts, verify with a second request
            logger.info(f"Low count ({count}) detected, verifying...")
            time.sleep(self.verification_delay)
            verify_response = self._make_request("esearch.fcgi", params)
            verify_data = verify_response.json()
            verify_count = int(verify_data["esearchresult"]["count"])
            
            if verify_count != count:
                logger.warning(f"Count mismatch: {count} vs {verify_count}. Using higher value.")
                count = max(count, verify_count)
            
            logger.info(f"Final count for query: {count}")
            return count
            
        except Exception as e:
            logger.error(f"Error getting count for {query} in {year}: {str(e)}")
            return 0

    def get_publication_counts_by_year(self, topic: str, manufacturers: List[str], 
                                     start_year: int, end_year: int) -> Dict:
        """Get publication counts with progress tracking"""
        config = self._load_company_config()
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

        total_operations = len(results["years"]) * len(sorted_manufacturers)
        current_operation = 0
        
        for year in results["years"]:
            results["counts"][year] = {}
            results["totals_by_year"][year] = 0
            
            for manufacturer in sorted_manufacturers:
                self._update_progress(
                    current_operation,
                    total_operations,
                    f"Processing {manufacturer} for year {year} (operation {current_operation + 1}/{total_operations})"
                )
                
                # Add extra delay between manufacturers
                if current_operation > 0:
                    time.sleep(1.0)  # Additional delay between different searches
                
                count = self.get_publication_count(topic, year, manufacturer)
                results["counts"][year][manufacturer] = count
                results["totals_by_year"][year] += count
                
                if manufacturer not in results["totals_by_manufacturer"]:
                    results["totals_by_manufacturer"][manufacturer] = 0
                results["totals_by_manufacturer"][manufacturer] += count
                
                current_operation += 1
                logger.info(f"Completed {current_operation}/{total_operations} operations")

        self._update_progress(total_operations, total_operations, "Complete")
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

    def basic_search(self, query: str, start_year: int, end_year: int, 
                    page: int = 1, results_per_page: int = 20) -> Dict:
        """Perform a basic PubMed search with year range"""
        date_range = f"{start_year}/01/01[dp]:{end_year}/12/31[dp]"
        full_query = f"({query}) AND {date_range}"
        
        # First get PMIDs
        search_params = {
            "db": "pubmed",
            "term": full_query,
            "retmax": results_per_page,
            "retstart": (page - 1) * results_per_page,
            "retmode": "json"
        }
        
        try:
            search_response = self._make_request("esearch.fcgi", search_params)
            search_data = search_response.json()
            pmids = search_data["esearchresult"]["idlist"]
            total_count = int(search_data["esearchresult"]["count"])
            
            if not pmids:
                return {
                    "total_count": total_count,
                    "current_page": page,
                    "total_pages": (total_count + results_per_page - 1) // results_per_page,
                    "results": []
                }
            
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
                    "doi": article_data.get("doi", ""),
                    "abstract": article_data.get("abstract", "")
                })
            
            return {
                "total_count": total_count,
                "current_page": page,
                "total_pages": (total_count + results_per_page - 1) // results_per_page,
                "results": results
            }
            
        except Exception as e:
            print(f"Error performing basic search: {str(e)}")
            return {
                "error": str(e),
                "total_count": 0,
                "current_page": page,
                "total_pages": 0,
                "results": []
            } 