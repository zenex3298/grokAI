import os
import time
import requests
import json
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from datetime import datetime

from src.utils.logger import get_logger, LogComponent, set_context, log_data_metrics, log_function_call

# Get a logger specifically for the search component
logger = get_logger(LogComponent.SEARCH)

@log_function_call
def search_google(vendor_name, status_callback=None):
    """Search Google for customer information."""
    # Set the context for this operation
    set_context(vendor_name=vendor_name, operation="google_search_scrape")
    
    # Initialize metrics
    metrics = {
        'start_time': time.time(),
        'vendor_name': vendor_name,
        'queries_run': 0,
        'queries_successful': 0,
        'total_results': 0,
        'processed_results': 0,
        'customers_found': 0,
        'status': 'started',
        'using_api': False,
        'using_basic_search': False,
        'query_metrics': []
    }
    
    # Call status callback if provided
    if status_callback:
        status_callback(metrics)
    
    try:
        logger.info(f"Starting Google search for vendor: {vendor_name}", 
                  extra={'vendor_name': vendor_name})
        
        # Get API key and CX from environment
        api_key = os.environ.get('GOOGLE_API_KEY')
        cx = os.environ.get('GOOGLE_CX')
        
        if not api_key or not cx:
            logger.warning("Google API key or CX not found in environment variables, using limited search",
                         extra={'vendor_name': vendor_name, 'missing_config': not api_key and not cx})
            metrics['status'] = 'fallback_basic'
            metrics['using_basic_search'] = True
            
            # Call status callback if provided
            if status_callback:
                status_callback(metrics)
            
            # Log metrics and return basic search results
            metrics['end_time'] = time.time()
            metrics['duration'] = metrics['end_time'] - metrics['start_time']
            log_data_metrics(logger, "google_search_scrape", metrics)
            return basic_search(vendor_name, status_callback)
        
        metrics['using_api'] = True
        
        # Define search queries with different strategies
        queries = [
            f'"{vendor_name} customers"',
            f'"has chosen {vendor_name}"',
            f'"{vendor_name} case study"',
            f'"{vendor_name} success story"'
        ]
        
        # Track query success/failure
        query_metrics = []
        all_results = []
        
        for query_index, query in enumerate(queries):
            query_start = time.time()
            query_metric = {
                'query': query,
                'start_time': query_start,
                'results_count': 0,
                'customers_found': 0,
                'status': 'started'
            }
            
            logger.info(f"Searching Google for: {query}",
                       extra={'vendor_name': vendor_name, 'query': query, 'query_index': query_index})
            
            try:
                # Call Google Search API
                search_results = google_search(query)
                
                query_metric['results_count'] = len(search_results)
                metrics['total_results'] += len(search_results)
                
                if search_results:
                    query_metric['status'] = 'success'
                    metrics['queries_successful'] += 1
                    logger.info(f"Query returned {len(search_results)} results", 
                               extra={'count': len(search_results), 'query': query})
                else:
                    query_metric['status'] = 'empty'
                    logger.warning(f"Query returned no results", 
                                 extra={'query': query})
                
                # Process results
                for result_index, result in enumerate(search_results):
                    title = result.get("title", "")
                    snippet = result.get("snippet", "")
                    link = result.get("link", "")
                    
                    metrics['processed_results'] += 1
                    
                    # Skip results from the vendor's own website
                    parsed_url = urlparse(link)
                    domain = parsed_url.netloc
                    
                    # Log the full result details
                    logger.info(f"Processing search result {result_index+1}/{len(search_results)}: {json.dumps(result)}")
                    
                    logger.debug(f"Processing search result {result_index+1}/{len(search_results)}: {title}",
                               extra={'title': title, 'link': link, 'domain': domain})
                    
                    if vendor_name.lower().replace(" ", "") in domain:
                        logger.debug(f"Skipping result from vendor's own domain: {domain}",
                                   extra={'domain': domain, 'vendor_name': vendor_name})
                        continue
                    
                    # Multiple extraction strategies
                    customer_name = None
                    source_type = None
                    
                    # Strategy 1: Case study or success story in title
                    if "case study" in title.lower() or "success story" in title.lower():
                        parts = title.split("-")
                        if len(parts) > 1:
                            potential_customer = parts[0].strip()
                            if potential_customer and potential_customer.lower() != vendor_name.lower():
                                customer_name = potential_customer
                                source_type = "case_study_title"
                    
                    # Strategy 2: "Customer X uses/chose/selected Vendor Y" pattern
                    if not customer_name:
                        lower_title = title.lower()
                        lower_snippet = snippet.lower()
                        
                        if (f"chose {vendor_name.lower()}" in lower_title or 
                            f"selected {vendor_name.lower()}" in lower_title or
                            f"uses {vendor_name.lower()}" in lower_title or
                            f"chose {vendor_name.lower()}" in lower_snippet or
                            f"selected {vendor_name.lower()}" in lower_snippet or
                            f"uses {vendor_name.lower()}" in lower_snippet):
                            
                            # Try to extract customer name from title
                            parts = title.split(vendor_name, 1)[0].strip()
                            if parts and len(parts.split()) < 5:  # Avoid long phrases
                                customer_name = parts
                                source_type = "chose_pattern"
                    
                    # If we found a customer name, add it to results
                    if customer_name and customer_name.lower() != vendor_name.lower():
                        # Clean up name - remove common prefixes/suffixes
                        for prefix in ["how ", "why ", "when "]:
                            if customer_name.lower().startswith(prefix):
                                customer_name = customer_name[len(prefix):].strip()
                        
                        all_results.append({
                            "name": customer_name,
                            "url": domain if domain else None,
                            "source": f"Google Search - {query}"
                        })
                        logger.info(f"Found potential customer from Google: {customer_name}",
                                  extra={'customer_name': customer_name, 
                                         'source': source_type,
                                         'domain': domain,
                                         'query': query})
                        metrics['customers_found'] += 1
                        query_metric['customers_found'] += 1
                
            except Exception as e:
                logger.error(f"Error processing query '{query}': {str(e)}",
                           extra={'error_type': type(e).__name__, 
                                  'error_message': str(e),
                                  'query': query})
                query_metric['status'] = 'error'
                query_metric['error'] = f"{type(e).__name__}: {str(e)}"
            
            # Finalize query metrics
            query_metric['end_time'] = time.time()
            query_metric['duration'] = query_metric['end_time'] - query_metric['start_time']
            query_metrics.append(query_metric)
            
            # Call status callback if provided
            if status_callback:
                status_callback(metrics.copy())
                
            metrics['queries_run'] += 1
        
        # Store query metrics in the overall metrics
        metrics['query_metrics'] = query_metrics
        
        # Deduplicate results by customer name
        unique_customers = {}
        for result in all_results:
            name = result['name'].lower()
            if name not in unique_customers:
                unique_customers[name] = result
        
        deduplicated_results = list(unique_customers.values())
        metrics['unique_customers'] = len(deduplicated_results)
        
        # Final metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'success' if len(deduplicated_results) > 0 else 'empty'
        log_data_metrics(logger, "google_search_scrape", metrics)
        
        # Final status callback
        if status_callback:
            status_callback(metrics.copy())
        
        logger.info(f"Completed Google search for {vendor_name}. Found {len(deduplicated_results)} unique customers from {metrics['queries_successful']} successful queries.",
                  extra={'vendor_name': vendor_name, 
                         'customer_count': len(deduplicated_results),
                         'successful_queries': metrics['queries_successful']})
        
        return deduplicated_results
    
    except Exception as e:
        logger.exception(f"Error searching Google for {vendor_name}: {str(e)}",
                       extra={'error_type': type(e).__name__, 'error_message': str(e)})
        
        # Log failure metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'error'
        metrics['error_type'] = type(e).__name__
        metrics['error_message'] = str(e)
        log_data_metrics(logger, "google_search_scrape", metrics)
        
        # Error status callback
        if status_callback:
            status_callback(metrics.copy())
        
        return []

@log_function_call
def google_search(query: str) -> list:
    """Call Google Custom Search API."""
    api_metrics = {
        'start_time': time.time(),
        'query': query,
        'url': "https://www.googleapis.com/customsearch/v1",
        'status_code': 0,
        'results_count': 0,
        'status': 'started'
    }
    
    try:
        api_key = os.environ.get('GOOGLE_API_KEY')
        cx = os.environ.get('GOOGLE_CX')
        url = "https://www.googleapis.com/customsearch/v1"
        api_metrics['url'] = url
        
        params = {
            "key": api_key,
            "cx": cx,
            "q": query
        }
        
        logger.debug(f"Making Google API request for query: {query}", 
                   extra={'query': query, 'api_url': url})
        
        response_start = time.time()
        response = requests.get(url, params=params)
        api_metrics['response_time'] = time.time() - response_start
        api_metrics['status_code'] = response.status_code
        
        # Check response status
        if response.status_code != 200:
            logger.warning(f"Google API returned non-200 status: {response.status_code}",
                         extra={'status_code': response.status_code, 'query': query})
            api_metrics['status'] = 'error'
            api_metrics['error'] = f"HTTP {response.status_code}"
            
            response.raise_for_status()  # Will raise an exception
        
        # Parse JSON response
        json_start = time.time()
        result_json = response.json()
        api_metrics['json_parse_time'] = time.time() - json_start
        
        # Log the full raw response
        logger.info(f"Full Google API response: {json.dumps(result_json)}")
        
        # Extract and return items
        items = result_json.get("items", [])
        api_metrics['results_count'] = len(items)
        
        # Check if we have search information
        if 'searchInformation' in result_json:
            search_info = result_json['searchInformation']
            api_metrics['total_results'] = search_info.get('totalResults', '0')
            api_metrics['search_time'] = search_info.get('searchTime', 0)
            
            logger.debug(f"Google reports {api_metrics['total_results']} total results in {api_metrics['search_time']} seconds",
                       extra={'total_results': api_metrics['total_results'], 
                              'search_time': api_metrics['search_time']})
        
        # Success metrics
        api_metrics['end_time'] = time.time()
        api_metrics['duration'] = api_metrics['end_time'] - api_metrics['start_time']
        api_metrics['status'] = 'success'
        log_data_metrics(logger, "google_api_call", api_metrics)
        
        logger.info(f"Google API returned {len(items)} results for query: {query}",
                   extra={'count': len(items), 'query': query})
        
        return items
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error in Google search API call: {str(e)}",
                   extra={'error_type': type(e).__name__, 
                          'error_message': str(e),
                          'query': query})
        
        # Error metrics
        api_metrics['end_time'] = time.time()
        api_metrics['duration'] = api_metrics['end_time'] - api_metrics['start_time']
        api_metrics['status'] = 'error'
        api_metrics['error_type'] = type(e).__name__
        api_metrics['error_message'] = str(e)
        log_data_metrics(logger, "google_api_call", api_metrics)
        
        return []
        
    except ValueError as e:
        # JSON parsing error
        logger.error(f"JSON parsing error in Google search API call: {str(e)}",
                   extra={'error_type': 'JSONParseError', 
                          'error_message': str(e),
                          'query': query})
        
        # Error metrics
        api_metrics['end_time'] = time.time()
        api_metrics['duration'] = api_metrics['end_time'] - api_metrics['start_time']
        api_metrics['status'] = 'error'
        api_metrics['error_type'] = 'JSONParseError'
        api_metrics['error_message'] = str(e)
        log_data_metrics(logger, "google_api_call", api_metrics)
        
        return []
        
    except Exception as e:
        logger.exception(f"Error in Google search API call: {str(e)}",
                       extra={'error_type': type(e).__name__, 
                              'error_message': str(e),
                              'query': query})
        
        # Error metrics
        api_metrics['end_time'] = time.time()
        api_metrics['duration'] = api_metrics['end_time'] - api_metrics['start_time']
        api_metrics['status'] = 'error'
        api_metrics['error_type'] = type(e).__name__
        api_metrics['error_message'] = str(e)
        log_data_metrics(logger, "google_api_call", api_metrics)
        
        return []

@log_function_call
def basic_search(vendor_name, status_callback=None):
    """Basic search function without using Google API."""
    # Set the context for this operation
    set_context(vendor_name=vendor_name, operation="basic_search")
    
    # Initialize metrics
    metrics = {
        'start_time': time.time(),
        'vendor_name': vendor_name,
        'status': 'started'
    }
    
    # Initial status callback
    if status_callback:
        status_callback(metrics.copy())
    
    try:
        logger.warning("Using basic search function - limited results",
                     extra={'vendor_name': vendor_name})
        
        # Add some dummy results for common cloud vendors
        results = []
        
        if vendor_name.lower() in ["aws", "amazon web services"]:
            results = [
                {"name": "Netflix", "url": "netflix.com", "source": "Basic Search"},
                {"name": "Airbnb", "url": "airbnb.com", "source": "Basic Search"},
                {"name": "Lyft", "url": "lyft.com", "source": "Basic Search"}
            ]
        elif vendor_name.lower() in ["google cloud", "gcp"]:
            results = [
                {"name": "Spotify", "url": "spotify.com", "source": "Basic Search"},
                {"name": "Twitter", "url": "twitter.com", "source": "Basic Search"},
                {"name": "Snapchat", "url": "snapchat.com", "source": "Basic Search"}
            ]
        elif vendor_name.lower() in ["azure", "microsoft azure"]:
            results = [
                {"name": "Adobe", "url": "adobe.com", "source": "Basic Search"},
                {"name": "HP", "url": "hp.com", "source": "Basic Search"},
                {"name": "Walmart", "url": "walmart.com", "source": "Basic Search"}
            ]
        else:
            # Default placeholder result
            results = [{
                "name": "Example Customer",
                "url": "example.com",
                "source": "Basic Search (Placeholder)"
            }]
        
        # Log success
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'success'
        metrics['results_count'] = len(results)
        metrics['unique_customers'] = len(results)
        log_data_metrics(logger, "basic_search", metrics)
        
        # Final status callback
        if status_callback:
            status_callback(metrics.copy())
        
        logger.info(f"Basic search returning {len(results)} results for {vendor_name}",
                  extra={'vendor_name': vendor_name, 'count': len(results)})
        
        return results
        
    except Exception as e:
        logger.exception(f"Error in basic search: {str(e)}",
                       extra={'error_type': type(e).__name__, 'error_message': str(e)})
        
        # Error metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'error'
        metrics['error_type'] = type(e).__name__
        metrics['error_message'] = str(e)
        log_data_metrics(logger, "basic_search", metrics)
        
        # Error status callback
        if status_callback:
            status_callback(metrics.copy())
        
        # Return empty list on error
        return []