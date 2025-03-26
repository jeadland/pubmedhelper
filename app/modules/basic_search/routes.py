from flask import render_template, request, jsonify, current_app, flash
from app.modules.basic_search import bp
import requests
import os
import pandas as pd
from urllib.parse import quote
import xml.etree.ElementTree as ET
from datetime import datetime
import math
import time

def parse_pubmed_article(article):
    """
    Parse a PubMed article XML element and extract relevant information
    """
    try:
        # Get PMID
        pmid = article.find('.//PMID').text if article.find('.//PMID') is not None else ''
        
        # Get Title
        title = article.find('.//ArticleTitle').text if article.find('.//ArticleTitle') is not None else 'No Title'
        
        # Get Authors with Affiliations
        author_list = article.findall('.//Author')
        authors = []
        affiliations = set()
        for author in author_list:
            last_name = author.find('LastName').text if author.find('LastName') is not None else ''
            fore_name = author.find('ForeName').text if author.find('ForeName') is not None else ''
            
            # Get author affiliations
            author_affiliations = author.findall('.//Affiliation')
            for affiliation in author_affiliations:
                if affiliation is not None and affiliation.text:
                    affiliations.add(affiliation.text)
            
            authors.append(f"{last_name}, {fore_name}".strip(', '))
        authors_str = '; '.join(authors) if authors else 'No Authors Listed'
        affiliations_str = '; '.join(affiliations) if affiliations else 'No Affiliations Listed'
        
        # Get Journal info
        journal_element = article.find('.//Journal')
        if journal_element is not None:
            journal_title = journal_element.find('.//Title').text if journal_element.find('.//Title') is not None else ''
            pub_date = journal_element.find('.//PubDate')
            if pub_date is not None:
                year = pub_date.find('Year').text if pub_date.find('Year') is not None else ''
                month = pub_date.find('Month').text if pub_date.find('Month') is not None else ''
                day = pub_date.find('Day').text if pub_date.find('Day') is not None else ''
                pub_date_str = f"{year} {month} {day}".strip()
            else:
                pub_date_str = 'No Date'
        else:
            journal_title = 'No Journal'
            pub_date_str = 'No Date'
        
        # Get Abstract
        abstract_element = article.find('.//Abstract')
        abstract = abstract_element.find('.//AbstractText').text if abstract_element is not None and abstract_element.find('.//AbstractText') is not None else 'No Abstract'
        
        # Get Grant Information
        grants = []
        grant_list = article.findall('.//Grant')
        for grant in grant_list:
            grant_id = grant.find('GrantID')
            agency = grant.find('Agency')
            if grant_id is not None or agency is not None:
                grant_info = {
                    'id': grant_id.text if grant_id is not None else '',
                    'agency': agency.text if agency is not None else ''
                }
                grants.append(grant_info)
        
        # Get MeSH Terms
        mesh_terms = []
        mesh_headings = article.findall('.//MeshHeading')
        for mesh in mesh_headings:
            descriptor = mesh.find('DescriptorName')
            if descriptor is not None:
                mesh_terms.append(descriptor.text)
        
        # Get Keywords
        keywords = []
        keyword_list = article.findall('.//Keyword')
        for keyword in keyword_list:
            if keyword is not None and keyword.text:
                keywords.append(keyword.text)
        
        # Get Publication Types
        pub_types = []
        publication_types = article.findall('.//PublicationType')
        for pub_type in publication_types:
            if pub_type is not None and pub_type.text:
                pub_types.append(pub_type.text)
        
        return {
            'PMID': pmid,
            'Title': title,
            'Authors': authors_str,
            'Affiliations': affiliations_str,
            'Journal': journal_title,
            'Publication_Date': pub_date_str,
            'Abstract': abstract,
            'Grants': grants,
            'MeSH_Terms': mesh_terms,
            'Keywords': keywords,
            'Publication_Types': pub_types
        }
    except Exception as e:
        current_app.logger.error(f"Error parsing article: {str(e)}")
        return None

def build_search_query(query, search_type=None, year_from=None, year_to=None, grant_number=None, publication_type=None, mesh_terms=None):
    """
    Build a PubMed search query based on the search type and filters
    Following PubMed's search syntax rules:
    - Date format: YYYY/MM/DD[dp]
    - Field tags in square brackets
    - Proper handling of author names and journal titles
    """
    query_parts = []
    
    # Add main query with search type
    if search_type == 'author':
        # Handle author names according to PubMed rules
        # Remove punctuation and handle suffixes properly
        clean_query = query.replace('.', ' ').strip()
        if ',' in clean_query:  # Last name, First name format
            query_parts.append(f"{clean_query}[Author]")
        else:  # Natural order format
            query_parts.append(f"{clean_query}[Author]")
    elif search_type == 'journal':
        # Journal titles can be searched with full name or abbreviation
        query_parts.append(f"{query}[Journal]")
    elif search_type == 'affiliation':
        query_parts.append(f"{query}[Affiliation]")
    else:
        # For general search, let PubMed's automatic term mapping work
        query_parts.append(query)
    
    # Add filters using proper field tags
    if grant_number:
        query_parts.append(f"{grant_number}[Grant Number]")
    if publication_type:
        query_parts.append(f"{publication_type}[Publication Type]")
    if mesh_terms:
        # Handle multiple MeSH terms if provided
        mesh_terms_list = [term.strip() for term in mesh_terms.split(',')]
        mesh_parts = [f"{term}[MeSH Terms]" for term in mesh_terms_list if term]
        if mesh_parts:
            query_parts.append('(' + ' AND '.join(mesh_parts) + ')')
    
    # Handle date range using PubMed's date field syntax
    if year_from or year_to:
        if year_from and year_to:
            # Use proper date range format: YYYY:YYYY[dp]
            query_parts.append(f"{year_from}:{year_to}[dp]")
        elif year_from:
            # From specific year to present
            query_parts.append(f"{year_from}:3000[dp]")
        else:
            # Up to specific year
            query_parts.append(f"1800:{year_to}[dp]")
    
    # Combine all parts with AND operator
    return ' AND '.join(query_parts)

def search_pubmed(query, api_key, page=1, results_per_page=10, search_type=None, filters=None, start_index=0):
    """
    Search PubMed using the E-utilities API with pagination
    If filters are provided, apply them to the search
    """
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    
    try:
        # Build the appropriate search query
        formatted_query = build_search_query(query, search_type, filters)
        
        # Properly encode the query for URL
        encoded_query = quote(formatted_query)
        
        # First, search for IDs and get total count
        search_url = f"{base_url}esearch.fcgi"
        search_params = {
            'db': 'pubmed',
            'term': encoded_query,
            'retmax': 100,  # Fetch more results for stats
            'retstart': start_index,
            'api_key': api_key,
            'retmode': 'json',
            'usehistory': 'y'  # Use WebEnv for better reliability
        }
        
        # Add rate limiting delay
        time.sleep(0.34)  # ~3 requests per second
        
        response = requests.get(search_url, params=search_params)
        response.raise_for_status()
        
        try:
            search_data = response.json()
        except requests.exceptions.JSONDecodeError as e:
            current_app.logger.error(f"JSON decode error: {str(e)}")
            current_app.logger.error(f"Response content: {response.content}")
            raise ValueError("Invalid response format from PubMed")
        
        if 'esearchresult' not in search_data:
            raise ValueError("Invalid response structure from PubMed")
            
        total_results = int(search_data['esearchresult'].get('count', 0))
        pmids = search_data['esearchresult'].get('idlist', [])
        
        if not pmids:
            return [], 0, 0
            
        # Get WebEnv and query_key for reliable retrieval
        webenv = search_data['esearchresult'].get('webenv', '')
        query_key = search_data['esearchresult'].get('querykey', '')
        
        # Then fetch details for these IDs using WebEnv
        fetch_url = f"{base_url}efetch.fcgi"
        fetch_params = {
            'db': 'pubmed',
            'WebEnv': webenv,
            'query_key': query_key,
            'retmode': 'xml',
            'api_key': api_key,
            'retstart': start_index,
            'retmax': results_per_page
        }
        
        # Add rate limiting delay
        time.sleep(0.34)  # ~3 requests per second
        
        response = requests.get(fetch_url, params=fetch_params)
        response.raise_for_status()
        
        # Parse XML response
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            current_app.logger.error(f"XML parse error: {str(e)}")
            current_app.logger.error(f"Response content: {response.content}")
            raise ValueError("Invalid XML response from PubMed")
            
        articles = root.findall('.//PubmedArticle')
        
        results = []
        for article in articles:
            article_data = parse_pubmed_article(article)
            if article_data:  # Only add if parsing was successful
                results.append(article_data)
        
        total_pages = math.ceil(total_results / results_per_page)
        
        return results, total_pages, total_results
        
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Error searching PubMed: {str(e)}")
        current_app.logger.error(f"Query: {formatted_query}")
        current_app.logger.error(f"Encoded query: {encoded_query}")
        flash(f"Error connecting to PubMed: {str(e)}", "error")
        return [], 0, 0
    except (ET.ParseError, ValueError) as e:
        current_app.logger.error(f"Error processing response: {str(e)}")
        flash(f"Error processing results: {str(e)}", "error")
        return [], 0, 0
    except Exception as e:
        current_app.logger.error(f"Unexpected error: {str(e)}")
        flash("An unexpected error occurred", "error")
        return [], 0, 0

def collect_statistics(query, api_key, search_type=None, filters=None, max_samples=10000):
    """
    Collect statistics from samples across the entire result set
    Increased sample size with rate limiting
    """
    # First get total results count
    _, _, total_results = search_pubmed(query, api_key, page=1, search_type=search_type, filters=filters)
    
    if total_results == 0:
        return {}, {}, {}, {}
    
    # Calculate how many samples we'll take and their size
    max_results_per_call = 100  # PubMed API limit per request
    num_samples = min(max_samples // max_results_per_call, math.ceil(total_results / max_results_per_call))
    
    year_stats = {}
    author_stats = {}
    journal_stats = {}
    affiliation_stats = {}
    grant_stats = {}
    mesh_stats = {}
    
    # Calculate sampling points spread across the result set
    for i in range(num_samples):
        start_index = (i * (total_results // num_samples))
        
        # Rate limiting - sleep for 0.34 seconds (approximately 3 requests per second)
        time.sleep(0.34)
        
        try:
            # Make the API call with the calculated start index
            results, _, _ = search_pubmed(query, api_key, page=1, results_per_page=max_results_per_call, 
                                        search_type=search_type, filters=filters, start_index=start_index)
            
            # Process this batch of results
            for result in results:
                if not result:
                    continue
                
                # Year statistics
                try:
                    year = result['Publication_Date'].split()[0]
                    if year.isdigit():
                        year_stats[year] = year_stats.get(year, 0) + 1
                except (IndexError, AttributeError):
                    pass
                
                # Author statistics
                authors = result['Authors'].split('; ')
                for author in authors:
                    if author != 'No Authors Listed':
                        author_stats[author] = author_stats.get(author, 0) + 1
                
                # Journal statistics
                if result['Journal'] != 'No Journal':
                    journal_stats[result['Journal']] = journal_stats.get(result['Journal'], 0) + 1
                
                # Affiliation statistics
                affiliations = result['Affiliations'].split('; ')
                for affiliation in affiliations:
                    if affiliation != 'No Affiliations Listed':
                        affiliation_stats[affiliation] = affiliation_stats.get(affiliation, 0) + 1
                
                # Grant statistics
                for grant in result['Grants']:
                    if grant['id']:
                        grant_stats[f"{grant['id']} ({grant['agency']})"] = \
                            grant_stats.get(f"{grant['id']} ({grant['agency']})", 0) + 1
                
                # MeSH Term statistics
                for term in result['MeSH_Terms']:
                    mesh_stats[term] = mesh_stats.get(term, 0) + 1
                    
        except Exception as e:
            current_app.logger.error(f"Error collecting statistics batch {i}: {str(e)}")
            continue
    
    # Sort statistics
    year_stats = dict(sorted(year_stats.items(), key=lambda x: x[0], reverse=True))
    top_authors = dict(sorted(author_stats.items(), key=lambda x: x[1], reverse=True)[:10])
    top_journals = dict(sorted(journal_stats.items(), key=lambda x: x[1], reverse=True)[:10])
    top_affiliations = dict(sorted(affiliation_stats.items(), key=lambda x: x[1], reverse=True)[:10])
    top_grants = dict(sorted(grant_stats.items(), key=lambda x: x[1], reverse=True)[:10])
    top_mesh_terms = dict(sorted(mesh_stats.items(), key=lambda x: x[1], reverse=True)[:10])
    
    # Add sampling information
    sampling_info = {
        'total_results': total_results,
        'sampled_results': num_samples * max_results_per_call,
        'sampling_percentage': round((num_samples * max_results_per_call / total_results) * 100, 2)
    }
    
    all_stats = {
        'year_stats': year_stats,
        'top_authors': top_authors,
        'top_journals': top_journals,
        'top_affiliations': top_affiliations,
        'top_grants': top_grants,
        'top_mesh_terms': top_mesh_terms
    }
    
    return all_stats, sampling_info

@bp.route('/', methods=['GET'])
def index():
    query = request.args.get('query', '').strip()
    search_type = request.args.get('search_type', '')
    year_from = request.args.get('year_from', '')
    year_to = request.args.get('year_to', '')
    grant_number = request.args.get('grant_number', '')
    publication_type = request.args.get('publication_type', '')
    mesh_terms = request.args.get('mesh_terms', '')
    
    # Get the current page from query parameters
    try:
        current_page = int(request.args.get('page', 1))
        if current_page < 1:
            current_page = 1
    except ValueError:
        current_page = 1

    # Initialize all variables with default values
    total_results = 0
    total_pages = 0
    page_range = range(0)
    articles = []
    year_stats = {}
    top_authors = {}
    top_journals = {}
    top_affiliations = {}
    top_grants = {}
    top_mesh_terms = {}
    sampling_info = None
    formatted_query = None

    if not query:
        return render_template('basic_search/index.html',
                             query=query,
                             search_type=search_type,
                             total_results=total_results,
                             total_pages=total_pages,
                             current_page=current_page,
                             page_range=page_range,
                             articles=articles,
                             formatted_query=formatted_query)

    try:
        api_key = os.getenv('PUBMED_API_KEY')
        if not api_key:
            flash("PubMed API key is not configured", "error")
            return render_template('basic_search/index.html',
                                 query=query,
                                 search_type=search_type,
                                 total_results=total_results,
                                 total_pages=total_pages,
                                 current_page=current_page,
                                 page_range=page_range,
                                 articles=articles,
                                 formatted_query=formatted_query)

        # Build search query with filters
        formatted_query = build_search_query(
            query, 
            search_type=search_type,
            year_from=year_from,
            year_to=year_to,
            grant_number=grant_number,
            publication_type=publication_type,
            mesh_terms=mesh_terms
        )

        # Get initial results and total count
        articles, total_pages, total_results = search_pubmed(formatted_query, api_key, current_page)

        if total_results == 0:
            flash('No results found for your query.', 'warning')
            return render_template('basic_search/index.html',
                                 query=query,
                                 search_type=search_type,
                                 total_results=total_results,
                                 total_pages=total_pages,
                                 current_page=current_page,
                                 page_range=page_range,
                                 articles=articles,
                                 formatted_query=formatted_query)

        # Calculate pagination range
        start_page = max(1, current_page - 2)
        end_page = min(total_pages + 1, current_page + 3)
        page_range = range(start_page, end_page)

        # Collect statistics from sampled results
        stats_results, sampling_info = collect_statistics(formatted_query, api_key, search_type)
        
        # Update statistics from the results
        if stats_results:
            year_stats = stats_results.get('year_stats', {})
            top_authors = stats_results.get('top_authors', {})
            top_journals = stats_results.get('top_journals', {})
            top_affiliations = stats_results.get('top_affiliations', {})
            top_grants = stats_results.get('top_grants', {})
            top_mesh_terms = stats_results.get('top_mesh_terms', {})

        return render_template('basic_search/index.html',
                             query=query,
                             search_type=search_type,
                             total_results=total_results,
                             total_pages=total_pages,
                             current_page=current_page,
                             page_range=page_range,
                             articles=articles,
                             year_stats=year_stats,
                             top_authors=top_authors,
                             top_journals=top_journals,
                             top_affiliations=top_affiliations,
                             top_grants=top_grants,
                             top_mesh_terms=top_mesh_terms,
                             sampling_info=sampling_info,
                             formatted_query=formatted_query)

    except Exception as e:
        current_app.logger.error(f"Search error: {str(e)}")
        flash(f"An error occurred while searching: {str(e)}", 'error')
        return render_template('basic_search/index.html',
                             query=query,
                             search_type=search_type,
                             total_results=total_results,
                             total_pages=total_pages,
                             current_page=current_page,
                             page_range=page_range,
                             articles=articles,
                             formatted_query=formatted_query) 