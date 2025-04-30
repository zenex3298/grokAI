import requests
import time
from bs4 import BeautifulSoup
from datetime import datetime

from src.utils.logger import get_logger, LogComponent, set_context, log_data_metrics, log_function_call
from src.analyzers.grok_analyzer import cleanup_url

# Get a logger specifically for the featured customers component
logger = get_logger(LogComponent.FEATURED)

@log_function_call
def scrape_featured_customers(vendor_name, max_results=20, status_callback=None):
    """Scrape FeaturedCustomers.com for information about the vendor's customers.
    
    Args:
        vendor_name: Name of the vendor to search for
        max_results: Maximum number of results to return (default: 20)
        status_callback: Optional callback function to update processing status
    
    Returns:
        List of dictionaries containing customer data with name, url, and source fields
    """
    # Set the context for this operation
    set_context(vendor_name=vendor_name, operation="featured_customers_scrape")
    
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
        'sections_found': 0,
        'customers_found': 0,
        'status': 'started',
        'has_vendor_profile': False,
        'target_count': max_results
    }
    
    # Update status if callback provided
    if status_callback:
        metrics['status'] = 'featured_customers_started'
        status_callback(metrics)
    
    try:
        # Try multiple URL patterns for Featured Customers
        search_urls = [
            f"https://www.featuredcustomers.com/vendors/all/all?q={vendor_name.replace(' ', '+')}",  # Primary format per user instruction
            f"https://www.featuredcustomers.com/vendors?q={vendor_name.replace(' ', '+')}",  # Alternative search format
            f"https://www.featuredcustomers.com/vendor/{vendor_name.lower().replace(' ', '-')}/customers",  # Direct format
            f"https://www.featuredcustomers.com/vendor/{vendor_name.lower().replace(' ', '')}/customers",   # Direct format without spaces
            f"https://www.featuredcustomers.com/vendor/{vendor_name.lower().replace(' ', '-')}"  # Base vendor profile
        ]
        
        # Set initial URL to try
        search_url = search_urls[0]
        metrics['search_url'] = search_url
        metrics['all_urls_tried'] = search_urls
        
        logger.info(f"Searching FeaturedCustomers starting with vendors/all/all URL pattern for: {vendor_name}", 
                  extra={'vendor_name': vendor_name, 'primary_url': search_url, 'all_urls': search_urls})
        
        # Update status if callback provided
        if status_callback:
            metrics['status'] = 'featured_customers_searching'
            metrics['current_page'] = search_url
            status_callback(metrics)
        
        # Make request to search page
        search_start = time.time()
        try:
            logger.debug(f"Making HTTP request to FeaturedCustomers vendors/all/all endpoint: {search_url}")
            response = requests.get(search_url, timeout=10)
            metrics['search_status_code'] = response.status_code
            metrics['search_time'] = time.time() - search_start
            
            if response.status_code != 200:
                logger.warning(f"Failed to access FeaturedCustomers, status code: {response.status_code}",
                             extra={'vendor_name': vendor_name, 'status_code': response.status_code, 'url': search_url})
                
                # Special handling for 410 Gone status - site structure might have changed
                if response.status_code == 410:
                    logger.warning("FeaturedCustomers returned 410 Gone. The site structure might have changed.")
                    metrics['status'] = 'failed'
                    metrics['failure_reason'] = "FeaturedCustomers API structure has changed (410 Gone)"
                else:
                    metrics['status'] = 'failed'
                    metrics['failure_reason'] = f"Search HTTP {response.status_code}"
                
                log_data_metrics(logger, "featured_customers_scrape", metrics)
                
                # Update status if callback provided
                if status_callback:
                    status_callback(metrics)
                
                return []
                
            logger.debug(f"Successfully loaded FeaturedCustomers vendors page ({len(response.text)} bytes)",
                       extra={'response_size': len(response.text)})
                       
            # Additional debugging to analyze response structure
            if 'vendor' in response.text.lower() or 'vendors' in response.text.lower():
                vendor_mentions = response.text.lower().count('vendor')
                vendors_mentions = response.text.lower().count('vendors')
                logger.debug(f"Found {vendor_mentions} mentions of 'vendor' and {vendors_mentions} mentions of 'vendors' in response",
                           extra={'vendor_mentions': vendor_mentions, 'vendors_mentions': vendors_mentions})
            
            # Check if this might be a SPA (Single Page Application)
            if 'react' in response.text.lower() or 'angular' in response.text.lower() or 'vue' in response.text.lower():
                logger.info("FeaturedCustomers appears to be a Single Page Application (SPA), which may require JavaScript rendering")
            
            # Check if we should try fallback URLs
            all_links = soup.find_all('a', href=True)
            if len(all_links) == 0 or response.status_code != 200:
                logger.info("Primary URL didn't yield links, trying fallback URLs")
                
                # Try the other URLs in our list
                for i, fallback_url in enumerate(search_urls[1:], start=1):
                    logger.info(f"Trying fallback URL #{i}: {fallback_url}")
                    
                    try:
                        fallback_response = requests.get(fallback_url, timeout=10)
                        fallback_status = fallback_response.status_code
                        
                        logger.info(f"Fallback URL #{i} status: {fallback_status}")
                        
                        if fallback_status == 200:
                            # Check if this response has more links
                            fallback_soup = BeautifulSoup(fallback_response.text, 'html.parser')
                            fallback_links = fallback_soup.find_all('a', href=True)
                            
                            logger.info(f"Fallback URL #{i} found {len(fallback_links)} links")
                            
                            if len(fallback_links) > len(all_links):
                                logger.info(f"Switching to fallback URL #{i} which has more links")
                                # Use this response instead
                                response = fallback_response
                                soup = fallback_soup
                                search_url = fallback_url
                                metrics['search_url'] = fallback_url
                                metrics['fallback_used'] = True
                                metrics['fallback_index'] = i
                                break
                    except Exception as e:
                        logger.warning(f"Fallback URL #{i} error: {str(e)}")
                        continue
            
            # Check for JSON data that might contain profile information
            json_start = response.text.find('{')
            json_end = response.text.rfind('}')
            if json_start >= 0 and json_end > json_start:
                try:
                    # Extract the JSON part and log it for analysis
                    json_part = response.text[json_start:json_end+1]
                    if len(json_part) < 1000:  # Only log reasonable-sized JSON
                        logger.debug(f"Found potential JSON data: {json_part}")
                except Exception as json_err:
                    logger.debug(f"Error parsing JSON data: {str(json_err)}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error accessing FeaturedCustomers vendors endpoint: {str(e)}",
                       extra={'error_type': type(e).__name__, 'url': search_url})
            metrics['status'] = 'failed'
            metrics['failure_reason'] = f"Search request error: {type(e).__name__}"
            log_data_metrics(logger, "featured_customers_scrape", metrics)
            
            # Update status if callback provided
            if status_callback:
                status_callback(metrics)
            
            return []
        
        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Update status if callback provided
        if status_callback:
            metrics['status'] = 'featured_customers_parsing_search'
            status_callback(metrics)
        
        # Find vendor profile link (if exists)
        logger.debug(f"Searching for vendor profile for {vendor_name} in search results")
        vendor_profile = None
        vendor_slug = vendor_name.lower().replace(' ', '-')
        
        # For debugging purposes, log all links found in the response
        all_links = soup.find_all('a', href=True)
        logger.debug(f"Found {len(all_links)} links in the response")
        
        # Log a sample of the first 10 links for debugging
        link_sample = [(link['href'], link.get_text().strip()[:30]) for link in all_links[:10]]
        logger.debug(f"Sample of first 10 links: {link_sample}")
        
        # Track all potential matching links for diagnostics
        potential_links = []
        
        # Look for links to vendor profiles - format could be either /vendor/ or /vendors/ with the updated endpoint
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text().lower()
            
            # Check for both old and new URL formats
            # More flexible matching to catch different HTML structures
            if (f"/vendor/{vendor_slug}" in href or 
                f"/vendors/{vendor_slug}" in href or
                f"vendors/{vendor_slug}" in href or
                vendor_name.lower() in text or
                (vendor_name.lower() in href and ('profile' in href or 'vendor' in href))):
                
                match_type = 'unknown'
                if f"/vendor/{vendor_slug}" in href:
                    match_type = 'exact_old_format'
                elif f"/vendors/{vendor_slug}" in href:
                    match_type = 'exact_new_format'
                elif vendor_name.lower() in text:
                    match_type = 'partial_text_match'
                
                potential_links.append({
                    'href': href,
                    'text': text,
                    'match_type': match_type
                })
                
                if not vendor_profile:  # Take the first match
                    # Add domain if it's a relative URL
                    if href.startswith('/'):
                        vendor_profile = f"https://www.featuredcustomers.com{href}"
                    elif href.startswith('http'):
                        vendor_profile = href
                    else:
                        vendor_profile = f"https://www.featuredcustomers.com/{href}"
                        
                    logger.info(f"Found vendor profile: {vendor_profile}",
                               extra={'vendor_name': vendor_name, 'profile_url': vendor_profile, 'match_type': match_type})
        
        # Log all potential matches for diagnostics
        if len(potential_links) > 1:
            logger.debug(f"Found multiple potential profile links for {vendor_name}: {potential_links}",
                        extra={'vendor_name': vendor_name, 'link_count': len(potential_links)})
        
        # Check for vendor profile
        if not vendor_profile:
            logger.info(f"No vendor profile found for {vendor_name} on FeaturedCustomers",
                       extra={'vendor_name': vendor_name})
            metrics['status'] = 'no_profile'
            metrics['end_time'] = time.time()
            metrics['duration'] = metrics['end_time'] - metrics['start_time']
            log_data_metrics(logger, "featured_customers_scrape", metrics)
            
            # Update status if callback provided
            if status_callback:
                status_callback(metrics)
            
            return []
        
        metrics['has_vendor_profile'] = True
        metrics['profile_url'] = vendor_profile
        
        # Update status if callback provided
        if status_callback:
            metrics['status'] = 'featured_customers_accessing_profile'
            metrics['current_page'] = vendor_profile
            status_callback(metrics)
        
        # Access vendor profile
        profile_start = time.time()
        try:
            logger.debug(f"Making HTTP request to vendor profile: {vendor_profile}")
            profile_response = requests.get(vendor_profile, timeout=10)
            metrics['profile_status_code'] = profile_response.status_code
            metrics['profile_time'] = time.time() - profile_start
            
            if profile_response.status_code != 200:
                logger.warning(f"Failed to access vendor profile, status code: {profile_response.status_code}",
                             extra={'vendor_name': vendor_name, 'status_code': profile_response.status_code, 
                                    'url': vendor_profile})
                
                # Special handling for 410 Gone status - site structure might have changed
                if profile_response.status_code == 410:
                    logger.warning("FeaturedCustomers profile returned 410 Gone. The site structure might have changed.")
                    metrics['status'] = 'failed'
                    metrics['failure_reason'] = "FeaturedCustomers profile structure has changed (410 Gone)"
                else:
                    metrics['status'] = 'failed'
                    metrics['failure_reason'] = f"Profile HTTP {profile_response.status_code}"
                
                log_data_metrics(logger, "featured_customers_scrape", metrics)
                
                # Update status if callback provided
                if status_callback:
                    status_callback(metrics)
                
                return []
                
            logger.debug(f"Successfully loaded vendor profile page ({len(profile_response.text)} bytes)",
                       extra={'response_size': len(profile_response.text)})
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error accessing vendor profile: {str(e)}",
                       extra={'error_type': type(e).__name__, 'url': vendor_profile})
            metrics['status'] = 'failed'
            metrics['failure_reason'] = f"Profile request error: {type(e).__name__}"
            log_data_metrics(logger, "featured_customers_scrape", metrics)
            
            # Update status if callback provided
            if status_callback:
                status_callback(metrics)
            
            return []
        
        profile_soup = BeautifulSoup(profile_response.text, 'html.parser')
        
        # Update status if callback provided
        if status_callback:
            metrics['status'] = 'featured_customers_parsing_profile'
            status_callback(metrics)
        
        # Look for customer section
        logger.info(f"Searching for customer sections in vendor profile")
        customer_data = []
        
        # First, try to find the dedicated customers section
        customer_sections = profile_soup.find_all(['div', 'section'], 
                                                class_=lambda c: c and 'customer' in str(c).lower())
        
        metrics['sections_found'] = len(customer_sections)
        logger.debug(f"Found {len(customer_sections)} customer sections in profile",
                   extra={'section_count': len(customer_sections)})
        
        if len(customer_sections) == 0:
            # If no explicit customer sections, try to find testimonial or case study sections
            alt_sections = profile_soup.find_all(['div', 'section'], 
                                               class_=lambda c: c and any(term in str(c).lower() 
                                                                         for term in ['testimonial', 'case-study', 
                                                                                     'success-story']))
            
            if alt_sections:
                logger.info(f"No customer sections found, but found {len(alt_sections)} alternative sections")
                customer_sections = alt_sections
                metrics['sections_found'] = len(alt_sections)
                metrics['using_alternative_sections'] = True
        
        # Process each section
        for i, section in enumerate(customer_sections):
            section_id = section.get('id', f'section_{i}')
            section_class = section.get('class', ['unknown'])
            logger.debug(f"Processing customer section {i+1}/{len(customer_sections)}: {section_id} {section_class}")
            
            # Update status if callback provided
            if status_callback:
                metrics['status'] = 'featured_customers_processing_section'
                metrics['current_section'] = i + 1
                metrics['total_sections'] = len(customer_sections)
                status_callback(metrics)
            
            # Extract customer names
            customer_elems = section.find_all(['h3', 'h4', 'div', 'span'], 
                                            class_=lambda c: c and 'name' in str(c).lower())
            
            logger.debug(f"Found {len(customer_elems)} potential customer elements in section {i+1}",
                       extra={'section_index': i, 'element_count': len(customer_elems)})
            
            for customer_elem in customer_elems:
                name = customer_elem.get_text().strip()
                if name and len(name) > 2:
                    # Try to find associated URL
                    url = None
                    parent = customer_elem.parent
                    if parent:
                        link = parent.find('a', href=True)
                        if link and 'http' in link['href']:
                            url = cleanup_url(link['href'])  # Use the same cleanup as in other scraping
                            logger.debug(f"Found URL for customer {name}: {url}")
                    
                    customer_data.append({
                        'name': name,
                        'url': url,
                        'source': "FeaturedCustomers"
                    })
                    logger.info(f"Found customer from FeaturedCustomers: {name}",
                               extra={'customer_name': name, 'customer_url': url})
                    metrics['customers_found'] += 1
                    
                    # Update status if callback provided
                    if status_callback:
                        metrics['status'] = 'featured_customers_found'
                        metrics['companies_found'] = metrics['customers_found']
                        status_callback(metrics)
                    
                    # Check if we've reached the max_results
                    if metrics['customers_found'] >= max_results:
                        logger.info(f"Reached maximum result count ({max_results}), stopping search")
                        
                        # Add early exit metrics
                        metrics['early_exit'] = True
                        metrics['reason'] = f"Reached max_results: {max_results}"
                        
                        # Final metrics
                        metrics['end_time'] = time.time()
                        metrics['duration'] = metrics['end_time'] - metrics['start_time']
                        metrics['customers_found'] = len(customer_data)
                        metrics['status'] = 'success'
                        log_data_metrics(logger, "featured_customers_scrape", metrics)
                        
                        # Final status update
                        if status_callback:
                            metrics['status'] = 'complete'
                            status_callback(metrics)
                        
                        return customer_data[:max_results]  # Return only up to max_results
        
        # If no customers found via specific sections, try extracting from testimonials
        if len(customer_data) == 0:
            logger.info("No customers found in dedicated sections, trying to extract from testimonials")
            
            # Update status if callback provided
            if status_callback:
                metrics['status'] = 'featured_customers_searching_testimonials'
                status_callback(metrics)
            
            testimonials = profile_soup.find_all(['div', 'blockquote'], 
                                                class_=lambda c: c and 'testimonial' in str(c).lower())
            
            for i, testimonial in enumerate(testimonials):
                # Look for customer name in testimonial
                author = testimonial.find(['span', 'div', 'p'], 
                                        class_=lambda c: c and any(term in str(c).lower() 
                                                                  for term in ['author', 'name', 'company']))
                
                if author:
                    name = author.get_text().strip()
                    if name and len(name) > 2:
                        # Try to find associated URL
                        url = None
                        link = testimonial.find('a', href=True)
                        if link and 'http' in link['href']:
                            url = cleanup_url(link['href'])
                        
                        customer_data.append({
                            'name': name,
                            'url': url,
                            'source': "FeaturedCustomers - Testimonial"
                        })
                        logger.info(f"Found customer from testimonial: {name}",
                                  extra={'customer_name': name, 'source': 'testimonial'})
                        metrics['customers_found'] += 1
                        
                        # Update status if callback provided
                        if status_callback:
                            metrics['status'] = 'featured_customers_found'
                            metrics['companies_found'] = metrics['customers_found']
                            status_callback(metrics)
                        
                        # Check if we've reached the max_results
                        if metrics['customers_found'] >= max_results:
                            logger.info(f"Reached maximum result count ({max_results}), stopping search")
                            break
            
            metrics['extracted_from_testimonials'] = len(testimonials)
        
        # Final metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['customers_found'] = len(customer_data)
        metrics['status'] = 'success' if len(customer_data) > 0 else 'empty'
        log_data_metrics(logger, "featured_customers_scrape", metrics)
        
        logger.info(f"Completed FeaturedCustomers scraping for {vendor_name}. Found {len(customer_data)} customers.",
                  extra={'vendor_name': vendor_name, 'customer_count': len(customer_data)})
        
        # Final status update
        if status_callback:
            metrics['status'] = 'complete'
            metrics['companies_found'] = metrics['customers_found']
            status_callback(metrics)
        
        # Return all results up to max_results
        return customer_data[:max_results]
    
    except Exception as e:
        logger.exception(f"Error scraping FeaturedCustomers for {vendor_name}: {str(e)}",
                       extra={'error_type': type(e).__name__, 'error_message': str(e)})
        
        # Log failure metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'error'
        metrics['error_type'] = type(e).__name__
        metrics['error_message'] = str(e)
        log_data_metrics(logger, "featured_customers_scrape", metrics)
        
        # Final error status update
        if status_callback:
            metrics['status'] = 'error'
            status_callback(metrics)
        
        return []
