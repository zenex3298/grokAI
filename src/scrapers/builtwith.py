import requests
import time
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

from src.utils.logger import get_logger, LogComponent, set_context, log_data_metrics, log_function_call
from src.analyzers.grok_analyzer import analyze_with_grok
from src.utils.url_validator import validate_url

# Get a logger specifically for the BuiltWith component
logger = get_logger(LogComponent.SCRAPER)

@log_function_call
def scrape_builtwith(vendor_name, max_results=20, status_callback=None):
    """Scrape BuiltWith.com for information about the vendor's customers.
    
    Args:
        vendor_name: Name of the vendor to search for
        max_results: Maximum number of results to return (default: 20)
        status_callback: Optional callback function to update processing status
    
    Returns:
        List of dictionaries containing customer data with name, url, and source fields
    """
    # Set the context for this operation
    set_context(vendor_name=vendor_name, operation="builtwith_scrape")
    
    # Initialize metrics
    metrics = {
        'start_time': time.time(),
        'vendor_name': vendor_name,
        'search_url': '',
        'profile_url': '',
        'search_status_code': 0,
        'profile_status_code': 0,
        'search_time': 0,
        'profile_time': 0,
        'pages_processed': 0,
        'customers_found': 0,
        'status': 'started',
        'target_count': max_results
    }
    
    # Update status if callback provided
    if status_callback:
        metrics['status'] = 'builtwith_started'
        status_callback(metrics)
    
    try:
        # Create search URL
        encoded_term = quote_plus(vendor_name)
        search_url = f"https://builtwith.com/{encoded_term}"
        metrics['search_url'] = search_url
        
        logger.info(f"Searching BuiltWith for: {vendor_name}", 
                  extra={'vendor_name': vendor_name, 'search_url': search_url})
        
        # Update status if callback provided
        if status_callback:
            metrics['status'] = 'builtwith_searching'
            metrics['current_page'] = search_url
            status_callback(metrics)
        
        # Make request to search page
        search_start = time.time()
        try:
            logger.debug(f"Making HTTP request to BuiltWith search: {search_url}")
            
            # Use a realistic user agent to avoid being blocked
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://builtwith.com/'
            }
            
            response = requests.get(search_url, headers=headers, timeout=15)
            metrics['search_status_code'] = response.status_code
            metrics['search_time'] = time.time() - search_start
            
            if response.status_code != 200:
                logger.warning(f"Failed to access BuiltWith, status code: {response.status_code}",
                             extra={'vendor_name': vendor_name, 'status_code': response.status_code, 'url': search_url})
                
                metrics['status'] = 'failed'
                metrics['failure_reason'] = f"Search HTTP {response.status_code}"
                
                log_data_metrics(logger, "builtwith_scrape", metrics)
                
                # Update status if callback provided
                if status_callback:
                    status_callback(metrics)
                
                return []
                
            logger.debug(f"Successfully loaded BuiltWith search page ({len(response.text)} bytes)",
                       extra={'response_size': len(response.text)})
            
            # Update status if callback provided
            if status_callback:
                metrics['status'] = 'builtwith_parsing_search'
                status_callback(metrics)
            
            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Search results content
            search_results = []
            
            # Log the HTML structure for analysis
            logger.debug(f"Analyzing BuiltWith search results page structure")
            
            # Extract text from the page for Grok analysis
            page_content = soup.get_text()
            logger.info(f"Extracting text content from BuiltWith search page for analysis")
            
            # Create a structured data item for Grok analysis
            search_data = [{
                'name': 'BuiltWith Search Page',
                'url': search_url,
                'content': page_content,
                'source': 'BuiltWith'
            }]
            
            # Look for customer sections on the page - BuiltWith typically shows "Used By" or similar sections
            customer_sections = soup.find_all(['div', 'section'], 
                                         class_=lambda c: c and ('used by' in str(c).lower() or 
                                                               'customers' in str(c).lower() or
                                                               'client' in str(c).lower()))
            
            if customer_sections:
                logger.info(f"Found {len(customer_sections)} potential customer sections on search page")
                
                # Process each customer section to extract company info
                for section in customer_sections:
                    # Find all links within the section - these are often links to customer websites
                    customer_links = section.find_all('a')
                    for link in customer_links:
                        href = link.get('href', '')
                        company_name = link.get_text().strip()
                        
                        if href and company_name and len(company_name) > 2:
                            # Make sure the URL is an external link (not part of BuiltWith)
                            if not href.startswith('/') and 'builtwith.com' not in href:
                                search_results.append({
                                    'name': company_name,
                                    'url': href,
                                    'source': 'BuiltWith Direct'
                                })
                                metrics['customers_found'] += 1
                                
                                # Update status if callback provided
                                if status_callback:
                                    metrics['status'] = 'builtwith_customer_found'
                                    status_callback(metrics)
            
            # Update status if callback provided
            if status_callback:
                metrics['status'] = 'builtwith_analyzing'
                metrics['data_items'] = len(search_data)
                status_callback(metrics)
            
            # Send data to Grok for analysis if we have page content
            if search_data:
                logger.info(f"Sending {len(search_data)} BuiltWith data items to Grok for analysis")
                
                # Define progress callback for Grok analysis
                def grok_progress_callback(stage, partial_results=None, message=None):
                    if status_callback:
                        metrics['status'] = f'builtwith_grok_{stage}'
                        metrics['grok_stage'] = stage
                        metrics['grok_message'] = message
                        if partial_results:
                            metrics['customers_found'] = len(partial_results)
                        status_callback(metrics)
                
                # Define custom prompt for Grok
                custom_prompt = f"""
                Analyze this customer data for {vendor_name}:

                {{search_data}}

                TASK: ONLY extract EXISTING company names that are explicitly mentioned as customers or clients of {vendor_name}.

                CRITICAL INSTRUCTIONS:
                - DO NOT CHANGE ANYTHING - ONLY EXTRACT WHAT ALREADY EXISTS
                - DO NOT MAKE UP OR INVENT any company names
                - DO NOT include page titles, navigation items, or UI elements
                - DO NOT include the search terms themselves as results
                - DO NOT include "BuiltWith" itself as a company
                - DO NOT append ".com" to phrases that aren't actual companies
                - DO NOT create concatenated words by removing spaces
                - IF NO COMPANIES ARE FOUND, return an empty list - don't invent companies
                
                ONLY return companies that are EXPLICITLY mentioned as using {vendor_name}'s products or services.
                
                Please respond with each customer on a new line, following this format:
                Company Name, website_url (if available)

                If no legitimate companies are found, respond with:
                NO_COMPANIES_FOUND
                """
                
                # Use Grok to analyze the content with custom prompt
                grok_results = analyze_with_grok(search_data, vendor_name, grok_progress_callback, max_results, custom_prompt=custom_prompt)
                
                # Add any new results from Grok analysis
                for result in grok_results:
                    search_results.append({
                        'name': result.get('customer_name', ''),
                        'url': result.get('customer_url', None),
                        'source': 'BuiltWith via Grok'
                    })
            
            # Deduplicate results
            unique_results = {}
            for result in search_results:
                name = result.get('name', '').strip()
                if name.lower() not in unique_results and name.lower() != vendor_name.lower():
                    url = result.get('url')
                    if not url:
                        # Generate a URL if one doesn't exist
                        url = f"https://{name.lower().replace(' ', '')}.com"
                    validation_result = validate_url(url, validate_dns=False, validate_http=False)
                    unique_results[name.lower()] = {
                        'name': name,
                        'url': validation_result.cleaned_url if validation_result.structure_valid else None,
                        'source': 'BuiltWith'
                    }
            
            # Convert back to list
            final_results = list(unique_results.values())
            
            # Limit results if needed
            if len(final_results) > max_results:
                final_results = final_results[:max_results]
            
            # Final metrics
            metrics['end_time'] = time.time()
            metrics['duration'] = metrics['end_time'] - metrics['start_time']
            metrics['customers_found'] = len(final_results)
            metrics['status'] = 'success' if len(final_results) > 0 else 'empty'
            log_data_metrics(logger, "builtwith_scrape", metrics)
            
            logger.info(f"Completed BuiltWith scraping for {vendor_name}. Found {len(final_results)} customers.",
                      extra={'vendor_name': vendor_name, 'customer_count': len(final_results)})
            
            # Final status update
            if status_callback:
                metrics['status'] = 'complete'
                status_callback(metrics)
            
            return final_results
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error accessing BuiltWith search: {str(e)}",
                       extra={'error_type': type(e).__name__, 'url': search_url})
            metrics['status'] = 'failed'
            metrics['failure_reason'] = f"Search request error: {type(e).__name__}"
            log_data_metrics(logger, "builtwith_scrape", metrics)
            
            # Update status if callback provided
            if status_callback:
                status_callback(metrics)
            
            return []
    
    except Exception as e:
        logger.exception(f"Error scraping BuiltWith for {vendor_name}: {str(e)}",
                       extra={'error_type': type(e).__name__, 'error_message': str(e)})
        
        # Log failure metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'error'
        metrics['error_type'] = type(e).__name__
        metrics['error_message'] = str(e)
        log_data_metrics(logger, "builtwith_scrape", metrics)
        
        # Final error status update
        if status_callback:
            metrics['status'] = 'error'
            status_callback(metrics)
        
        return []