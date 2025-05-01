import requests
import time
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

from src.utils.logger import get_logger, LogComponent, set_context, log_data_metrics, log_function_call
from src.analyzers.grok_analyzer import analyze_with_grok, cleanup_url

# Get a logger specifically for the PublicWWW component
logger = get_logger(LogComponent.SCRAPER)

@log_function_call
def scrape_publicwww(vendor_name, max_results=20, status_callback=None):
    """Scrape PublicWWW.com for information about the vendor's customers.
    
    Args:
        vendor_name: Name of the vendor to search for
        max_results: Maximum number of results to return (default: 20)
        status_callback: Optional callback function to update processing status
    
    Returns:
        List of dictionaries containing customer data with name, url, and source fields
    """
    # Set the context for this operation
    set_context(vendor_name=vendor_name, operation="publicwww_scrape")
    
    # Initialize metrics
    metrics = {
        'start_time': time.time(),
        'vendor_name': vendor_name,
        'search_url': '',
        'search_status_code': 0,
        'search_time': 0,
        'pages_processed': 0,
        'sites_found': 0,
        'customers_found': 0,
        'status': 'started',
        'target_count': max_results
    }
    
    # Update status if callback provided
    if status_callback:
        metrics['status'] = 'publicwww_started'
        status_callback(metrics)
    
    try:
        # Create search URL
        # PublicWWW search requires a specific format - searching for vendor name in website code
        encoded_term = quote_plus(vendor_name)
        search_url = f"https://publicwww.com/websites/{encoded_term}/"
        metrics['search_url'] = search_url
        
        logger.info(f"Searching PublicWWW for: {vendor_name}", 
                  extra={'vendor_name': vendor_name, 'search_url': search_url})
        
        # Update status if callback provided
        if status_callback:
            metrics['status'] = 'publicwww_searching'
            metrics['current_page'] = search_url
            status_callback(metrics)
        
        # Make request to search page
        search_start = time.time()
        try:
            logger.debug(f"Making HTTP request to PublicWWW search: {search_url}")
            
            # Use a realistic user agent to avoid being blocked
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://publicwww.com/'
            }
            
            response = requests.get(search_url, headers=headers, timeout=15)
            metrics['search_status_code'] = response.status_code
            metrics['search_time'] = time.time() - search_start
            
            if response.status_code != 200:
                logger.warning(f"Failed to access PublicWWW, status code: {response.status_code}",
                             extra={'vendor_name': vendor_name, 'status_code': response.status_code, 'url': search_url})
                
                metrics['status'] = 'failed'
                metrics['failure_reason'] = f"Search HTTP {response.status_code}"
                
                log_data_metrics(logger, "publicwww_scrape", metrics)
                
                # Update status if callback provided
                if status_callback:
                    status_callback(metrics)
                
                return []
                
            logger.debug(f"Successfully loaded PublicWWW search page ({len(response.text)} bytes)",
                       extra={'response_size': len(response.text)})
            
            # Update status if callback provided
            if status_callback:
                metrics['status'] = 'publicwww_parsing_search'
                status_callback(metrics)
            
            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Search results content
            search_results = []
            
            # Log the HTML structure for analysis
            logger.debug(f"Analyzing PublicWWW search results page structure")
            
            # Extract text from the page for Grok analysis
            page_content = soup.get_text()
            logger.info(f"Extracting text content from PublicWWW search page for analysis")
            
            # Create a structured data item for Grok analysis
            search_data = [{
                'name': 'PublicWWW Search Page',
                'url': search_url,
                'content': page_content,
                'source': 'PublicWWW'
            }]
            
            # Look for result tables or lists
            # PublicWWW typically displays results in a table format with domain names
            result_elements = soup.find_all(['table', 'div'], 
                                       class_=lambda c: c and ('results' in str(c).lower() or 
                                                             'sites' in str(c).lower() or
                                                             'site-list' in str(c).lower()))
            
            if result_elements:
                logger.info(f"Found {len(result_elements)} result sections")
                
                # Process each result section to extract domains
                for section in result_elements:
                    # Find all links within the results
                    site_links = section.find_all('a', href=True)
                    
                    for link in site_links:
                        href = link.get('href', '')
                        site_name = link.get_text().strip()
                        
                        # Skip if it's a pagination link or internal PublicWWW link
                        if not href or 'publicwww.com' in href or not site_name:
                            continue
                            
                        # Clean up the URL and site name
                        if not href.startswith(('http://', 'https://')):
                            # If it's a relative URL, skip it as it's likely an internal link
                            if href.startswith('/'):
                                continue
                            # Otherwise, assume it's a domain and add https://
                            href = f"https://{href}"
                            
                        # Try to extract company name from domain
                        # This is a simple heuristic and might need improvement
                        domain_parts = href.split('/')[2].split('.')
                        if len(domain_parts) >= 2:
                            # Use the main part of the domain as company name if site_name is empty
                            if not site_name:
                                site_name = domain_parts[-2].capitalize()
                        
                        if site_name and len(site_name) > 2:
                            search_results.append({
                                'name': site_name,
                                'url': href,
                                'source': 'PublicWWW Direct'
                            })
                            metrics['sites_found'] += 1
                            
                            # Update status if callback provided
                            if status_callback:
                                metrics['status'] = 'publicwww_site_found'
                                status_callback(metrics)
            
            # Update status if callback provided
            if status_callback:
                metrics['status'] = 'publicwww_analyzing'
                metrics['data_items'] = len(search_data)
                status_callback(metrics)
            
            # Send data to Grok for analysis if we have page content
            if search_data:
                logger.info(f"Sending {len(search_data)} PublicWWW data items to Grok for analysis")
                
                # Define progress callback for Grok analysis
                def grok_progress_callback(stage, partial_results=None, message=None):
                    if status_callback:
                        metrics['status'] = f'publicwww_grok_{stage}'
                        metrics['grok_stage'] = stage
                        metrics['grok_message'] = message
                        if partial_results:
                            metrics['customers_found'] = len(partial_results)
                        status_callback(metrics)
                
                # Define custom prompt for Grok
                custom_prompt = f"""
                Analyze this data from PublicWWW for {vendor_name}:

                {{search_data}}

                TASK: ONLY extract EXISTING company names that are likely customers or clients of {vendor_name}.

                CRITICAL INSTRUCTIONS:
                - DO NOT CHANGE ANYTHING - ONLY EXTRACT WHAT ALREADY EXISTS
                - DO NOT MAKE UP OR INVENT any company names
                - DO NOT include page titles, navigation items, or UI elements
                - DO NOT include the search terms themselves as results
                - DO NOT include "PublicWWW" itself as a company
                - DO NOT append ".com" to phrases that aren't actual companies
                - DO NOT create concatenated words by removing spaces
                - IF NO COMPANIES ARE FOUND, return an empty list - don't invent companies
                
                The URLs shown are websites using {vendor_name} in their source code. These are likely customers or clients.
                Extract company names from domain names when needed.
                
                Please respond with each customer on a new line, following this format:
                Company Name, website_url

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
                        'source': 'PublicWWW via Grok'
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
                    unique_results[name.lower()] = {
                        'name': name,
                        'url': cleanup_url(url),
                        'source': 'PublicWWW'
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
            log_data_metrics(logger, "publicwww_scrape", metrics)
            
            logger.info(f"Completed PublicWWW scraping for {vendor_name}. Found {len(final_results)} customers.",
                      extra={'vendor_name': vendor_name, 'customer_count': len(final_results)})
            
            # Final status update
            if status_callback:
                metrics['status'] = 'complete'
                status_callback(metrics)
            
            return final_results
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error accessing PublicWWW search: {str(e)}",
                       extra={'error_type': type(e).__name__, 'url': search_url})
            metrics['status'] = 'failed'
            metrics['failure_reason'] = f"Search request error: {type(e).__name__}"
            log_data_metrics(logger, "publicwww_scrape", metrics)
            
            # Update status if callback provided
            if status_callback:
                status_callback(metrics)
            
            return []
    
    except Exception as e:
        logger.exception(f"Error scraping PublicWWW for {vendor_name}: {str(e)}",
                       extra={'error_type': type(e).__name__, 'error_message': str(e)})
        
        # Log failure metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'error'
        metrics['error_type'] = type(e).__name__
        metrics['error_message'] = str(e)
        log_data_metrics(logger, "publicwww_scrape", metrics)
        
        # Final error status update
        if status_callback:
            metrics['status'] = 'error'
            status_callback(metrics)
        
        return []