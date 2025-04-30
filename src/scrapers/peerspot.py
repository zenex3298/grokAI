import requests
import time
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

from src.utils.logger import get_logger, LogComponent, set_context, log_data_metrics, log_function_call
from src.analyzers.grok_analyzer import analyze_with_grok, cleanup_url

# Get a logger specifically for the PeerSpot component
logger = get_logger(LogComponent.SCRAPER)

@log_function_call
def scrape_peerspot(vendor_name, max_results=20, status_callback=None):
    """Scrape PeerSpot.com for information about the vendor's customers.
    
    Args:
        vendor_name: Name of the vendor to search for
        max_results: Maximum number of results to return (default: 20)
        status_callback: Optional callback function to update processing status
    
    Returns:
        List of dictionaries containing customer data with name, url, and source fields
    """
    # Set the context for this operation
    set_context(vendor_name=vendor_name, operation="peerspot_scrape")
    
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
        'reviews_found': 0,
        'customers_found': 0,
        'status': 'started',
        'target_count': max_results
    }
    
    # Update status if callback provided
    if status_callback:
        metrics['status'] = 'peerspot_started'
        status_callback(metrics)
    
    try:
        # Create search URL
        encoded_term = quote_plus(vendor_name)
        search_url = f"https://www.peerspot.com/search?search={encoded_term}&page=1"
        metrics['search_url'] = search_url
        
        logger.info(f"Searching PeerSpot for: {vendor_name}", 
                  extra={'vendor_name': vendor_name, 'search_url': search_url})
        
        # Update status if callback provided
        if status_callback:
            metrics['status'] = 'peerspot_searching'
            metrics['current_page'] = search_url
            status_callback(metrics)
        
        # Make request to search page
        search_start = time.time()
        try:
            logger.debug(f"Making HTTP request to PeerSpot search: {search_url}")
            response = requests.get(search_url, timeout=10)
            metrics['search_status_code'] = response.status_code
            metrics['search_time'] = time.time() - search_start
            
            if response.status_code != 200:
                logger.warning(f"Failed to access PeerSpot, status code: {response.status_code}",
                             extra={'vendor_name': vendor_name, 'status_code': response.status_code, 'url': search_url})
                
                metrics['status'] = 'failed'
                metrics['failure_reason'] = f"Search HTTP {response.status_code}"
                
                log_data_metrics(logger, "peerspot_scrape", metrics)
                
                # Update status if callback provided
                if status_callback:
                    status_callback(metrics)
                
                return []
                
            logger.debug(f"Successfully loaded PeerSpot search page ({len(response.text)} bytes)",
                       extra={'response_size': len(response.text)})
            
            # Update status if callback provided
            if status_callback:
                metrics['status'] = 'peerspot_parsing_search'
                status_callback(metrics)
            
            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Search results content
            search_results = []
            
            # Log the HTML structure for analysis
            logger.debug(f"Analyzing PeerSpot search results page structure")
            
            # Find product links in search results
            product_links = soup.find_all('a', href=lambda h: h and ('/products/' in h or '/categories/' in h))
            
            if product_links:
                logger.info(f"Found {len(product_links)} product links in search results")
                
                # Find the best product match (ideally the first one)
                vendor_profile_url = None
                
                for link in product_links:
                    href = link['href']
                    title = link.get_text().strip()
                    
                    # Check if this product title contains the vendor name
                    if vendor_name.lower() in title.lower():
                        # Make link absolute if it's relative
                        if href.startswith('/'):
                            vendor_profile_url = f"https://www.peerspot.com{href}"
                        else:
                            vendor_profile_url = href
                            
                        logger.info(f"Found vendor profile: {vendor_profile_url}")
                        metrics['profile_url'] = vendor_profile_url
                        break
                
                # If no explicit match found, use the first product
                if not vendor_profile_url and product_links:
                    first_link = product_links[0]
                    href = first_link['href']
                    
                    # Make link absolute if it's relative
                    if href.startswith('/'):
                        vendor_profile_url = f"https://www.peerspot.com{href}"
                    else:
                        vendor_profile_url = href
                        
                    logger.info(f"Using first product as vendor profile: {vendor_profile_url}")
                    metrics['profile_url'] = vendor_profile_url
                    metrics['used_first_result'] = True
            
            # Update status if callback provided
            if status_callback:
                metrics['status'] = 'peerspot_extracting'
                status_callback(metrics)
            
            # Extract full text from the page for Grok analysis
            page_content = soup.get_text()
            logger.info(f"Extracting text content from PeerSpot search page for analysis")
            
            # Create a structured data item for Grok analysis
            search_data = [{
                'name': 'PeerSpot Search Page',
                'url': search_url,
                'content': page_content,
                'source': 'PeerSpot'
            }]
            
            # Also look for review sections or testimonials on the search page
            review_sections = soup.find_all(['div', 'section'], 
                                         class_=lambda c: c and ('review' in str(c).lower() or 'testimonial' in str(c).lower()))
            
            if review_sections:
                logger.info(f"Found {len(review_sections)} review sections on search page")
                
                # Process each review section to extract reviewer company info
                for section in review_sections:
                    reviewer_info = section.find(['div', 'span'], 
                                             class_=lambda c: c and ('reviewer' in str(c).lower() or 'author' in str(c).lower()))
                    
                    if reviewer_info:
                        company_element = reviewer_info.find(['div', 'span'], 
                                                         class_=lambda c: c and ('company' in str(c).lower() or 'organization' in str(c).lower()))
                        
                        if company_element:
                            company_name = company_element.get_text().strip()
                            if company_name:
                                search_results.append({
                                    'name': company_name,
                                    'url': None,  # We don't have URLs from reviews directly
                                    'source': 'PeerSpot Review'
                                })
                                metrics['customers_found'] += 1
                                
                                # Update status if callback provided
                                if status_callback:
                                    metrics['status'] = 'peerspot_customer_found'
                                    status_callback(metrics)
            
            # If we found a vendor profile, get that page too
            if vendor_profile_url:
                logger.info(f"Accessing vendor profile page: {vendor_profile_url}")
                
                # Update status if callback provided
                if status_callback:
                    metrics['status'] = 'peerspot_accessing_profile'
                    metrics['current_page'] = vendor_profile_url
                    status_callback(metrics)
                
                try:
                    profile_start = time.time()
                    profile_response = requests.get(vendor_profile_url, timeout=10)
                    metrics['profile_status_code'] = profile_response.status_code
                    metrics['profile_time'] = time.time() - profile_start
                    
                    if profile_response.status_code == 200:
                        profile_soup = BeautifulSoup(profile_response.text, 'html.parser')
                        profile_content = profile_soup.get_text()
                        
                        # Add profile content for analysis
                        search_data.append({
                            'name': 'PeerSpot Profile Page',
                            'url': vendor_profile_url,
                            'content': profile_content,
                            'source': 'PeerSpot'
                        })
                        
                        # Also look for review sections on the profile page
                        profile_review_sections = profile_soup.find_all(['div', 'section'], 
                                                                    class_=lambda c: c and ('review' in str(c).lower() or 
                                                                                          'testimonial' in str(c).lower() or
                                                                                          'customer' in str(c).lower()))
                        
                        metrics['reviews_found'] = len(profile_review_sections)
                        logger.info(f"Found {len(profile_review_sections)} review sections on profile page")
                        
                        # Process each review section to extract reviewer company info
                        for section in profile_review_sections:
                            reviewer_info = section.find(['div', 'span'], 
                                                      class_=lambda c: c and ('reviewer' in str(c).lower() or 
                                                                           'author' in str(c).lower() or
                                                                           'company' in str(c).lower()))
                            
                            if reviewer_info:
                                company_name = reviewer_info.get_text().strip()
                                if company_name and len(company_name) > 2:
                                    search_results.append({
                                        'name': company_name,
                                        'url': None,  # We don't have URLs from reviews directly
                                        'source': 'PeerSpot Review'
                                    })
                                    metrics['customers_found'] += 1
                                    
                                    # Update status if callback provided
                                    if status_callback:
                                        metrics['status'] = 'peerspot_customer_found'
                                        status_callback(metrics)
                    else:
                        logger.warning(f"Failed to access vendor profile, status code: {profile_response.status_code}")
                        metrics['profile_error'] = f"HTTP {profile_response.status_code}"
                
                except Exception as e:
                    logger.error(f"Error accessing vendor profile: {str(e)}")
                    metrics['profile_error'] = str(e)
            
            # Update status if callback provided
            if status_callback:
                metrics['status'] = 'peerspot_analyzing'
                metrics['data_items'] = len(search_data)
                status_callback(metrics)
            
            # Send data to Grok for analysis if we have page content
            if search_data:
                logger.info(f"Sending {len(search_data)} PeerSpot data items to Grok for analysis")
                
                # Define progress callback for Grok analysis
                def grok_progress_callback(stage, partial_results=None, message=None):
                    if status_callback:
                        metrics['status'] = f'peerspot_grok_{stage}'
                        metrics['grok_stage'] = stage
                        metrics['grok_message'] = message
                        if partial_results:
                            metrics['customers_found'] = len(partial_results)
                        status_callback(metrics)
                
                # Define custom prompt for Grok
                custom_prompt = f"""
                Analyze this customer data for {vendor_name}:

                {search_data}

                TASK: ONLY extract EXISTING company names that are explicitly mentioned as customers or clients of {vendor_name}.

                CRITICAL INSTRUCTIONS:
                - DO NOT CHANGE ANYTHING - ONLY EXTRACT WHAT ALREADY EXISTS
                - DO NOT MAKE UP OR INVENT any company names
                - DO NOT include page titles, navigation items, or UI elements
                - DO NOT include the search terms themselves as results
                - DO NOT include "PeerSpot" itself as a company
                - DO NOT append ".com" to phrases that aren't actual companies
                - DO NOT create concatenated words by removing spaces
                - IF NO COMPANIES ARE FOUND, return an empty list - don't invent companies
                
                ONLY return companies that are EXPLICITLY mentioned as using {vendor_name}'s products or services.
                
                Please respond with each customer on a new line, following this format:
                Company Name

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
                        'source': 'PeerSpot via Grok'
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
                        'source': 'PeerSpot'
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
            log_data_metrics(logger, "peerspot_scrape", metrics)
            
            logger.info(f"Completed PeerSpot scraping for {vendor_name}. Found {len(final_results)} customers.",
                      extra={'vendor_name': vendor_name, 'customer_count': len(final_results)})
            
            # Final status update
            if status_callback:
                metrics['status'] = 'complete'
                status_callback(metrics)
            
            return final_results
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error accessing PeerSpot search: {str(e)}",
                       extra={'error_type': type(e).__name__, 'url': search_url})
            metrics['status'] = 'failed'
            metrics['failure_reason'] = f"Search request error: {type(e).__name__}"
            log_data_metrics(logger, "peerspot_scrape", metrics)
            
            # Update status if callback provided
            if status_callback:
                status_callback(metrics)
            
            return []
    
    except Exception as e:
        logger.exception(f"Error scraping PeerSpot for {vendor_name}: {str(e)}",
                       extra={'error_type': type(e).__name__, 'error_message': str(e)})
        
        # Log failure metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'error'
        metrics['error_type'] = type(e).__name__
        metrics['error_message'] = str(e)
        log_data_metrics(logger, "peerspot_scrape", metrics)
        
        # Final error status update
        if status_callback:
            metrics['status'] = 'error'
            status_callback(metrics)
        
        return []