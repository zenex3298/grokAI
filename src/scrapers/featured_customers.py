import requests
import time
from bs4 import BeautifulSoup
from datetime import datetime

from src.utils.logger import get_logger, LogComponent, set_context, log_data_metrics, log_function_call

# Get a logger specifically for the featured customers component
logger = get_logger(LogComponent.FEATURED)

@log_function_call
def scrape_featured_customers(vendor_name):
    """Scrape FeaturedCustomers.com for information about the vendor's customers."""
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
        'has_vendor_profile': False
    }
    
    try:
        # Create a search URL for Featured Customers
        search_url = f"https://www.featuredcustomers.com/search?q={vendor_name.replace(' ', '+')}" 
        metrics['search_url'] = search_url
        
        logger.info(f"Searching FeaturedCustomers for vendor: {vendor_name}", 
                  extra={'vendor_name': vendor_name, 'search_url': search_url})
        
        # Make request to search page
        search_start = time.time()
        try:
            logger.debug(f"Making HTTP request to FeaturedCustomers search: {search_url}")
            response = requests.get(search_url, timeout=10)
            metrics['search_status_code'] = response.status_code
            metrics['search_time'] = time.time() - search_start
            
            if response.status_code != 200:
                logger.warning(f"Failed to access FeaturedCustomers, status code: {response.status_code}",
                             extra={'vendor_name': vendor_name, 'status_code': response.status_code, 'url': search_url})
                metrics['status'] = 'failed'
                metrics['failure_reason'] = f"Search HTTP {response.status_code}"
                log_data_metrics(logger, "featured_customers_scrape", metrics)
                return []
                
            logger.debug(f"Successfully loaded FeaturedCustomers search page ({len(response.text)} bytes)",
                       extra={'response_size': len(response.text)})
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error accessing FeaturedCustomers search: {str(e)}",
                       extra={'error_type': type(e).__name__, 'url': search_url})
            metrics['status'] = 'failed'
            metrics['failure_reason'] = f"Search request error: {type(e).__name__}"
            log_data_metrics(logger, "featured_customers_scrape", metrics)
            return []
        
        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find vendor profile link (if exists)
        logger.debug(f"Searching for vendor profile for {vendor_name} in search results")
        vendor_profile = None
        vendor_slug = vendor_name.lower().replace(' ', '-')
        
        # Track all potential matching links for diagnostics
        potential_links = []
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text().lower()
            
            if f"/vendor/{vendor_slug}" in href or vendor_name.lower() in text:
                potential_links.append({
                    'href': href,
                    'text': text,
                    'match_type': 'exact' if f"/vendor/{vendor_slug}" in href else 'partial'
                })
                
                if not vendor_profile:  # Take the first match
                    vendor_profile = f"https://www.featuredcustomers.com{href}"
                    logger.info(f"Found vendor profile: {vendor_profile}",
                               extra={'vendor_name': vendor_name, 'profile_url': vendor_profile})
        
        # Log all potential matches for diagnostics
        if len(potential_links) > 1:
            logger.debug(f"Found multiple potential profile links for {vendor_name}: {potential_links}",
                        extra={'vendor_name': vendor_name, 'link_count': len(potential_links)})
        
        if not vendor_profile:
            logger.info(f"No vendor profile found for {vendor_name} on FeaturedCustomers",
                       extra={'vendor_name': vendor_name})
            metrics['status'] = 'no_profile'
            metrics['end_time'] = time.time()
            metrics['duration'] = metrics['end_time'] - metrics['start_time']
            log_data_metrics(logger, "featured_customers_scrape", metrics)
            return []
        
        metrics['has_vendor_profile'] = True
        metrics['profile_url'] = vendor_profile
        
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
                metrics['status'] = 'failed'
                metrics['failure_reason'] = f"Profile HTTP {profile_response.status_code}"
                log_data_metrics(logger, "featured_customers_scrape", metrics)
                return []
                
            logger.debug(f"Successfully loaded vendor profile page ({len(profile_response.text)} bytes)",
                       extra={'response_size': len(profile_response.text)})
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error accessing vendor profile: {str(e)}",
                       extra={'error_type': type(e).__name__, 'url': vendor_profile})
            metrics['status'] = 'failed'
            metrics['failure_reason'] = f"Profile request error: {type(e).__name__}"
            log_data_metrics(logger, "featured_customers_scrape", metrics)
            return []
        
        profile_soup = BeautifulSoup(profile_response.text, 'html.parser')
        
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
                            url = link['href']
                            logger.debug(f"Found URL for customer {name}: {url}")
                    
                    customer_data.append({
                        'name': name,
                        'url': url,
                        'source': "FeaturedCustomers"
                    })
                    logger.info(f"Found customer from FeaturedCustomers: {name}",
                               extra={'customer_name': name, 'customer_url': url})
                    metrics['customers_found'] += 1
        
        # If no customers found via specific sections, try extracting from testimonials
        if len(customer_data) == 0:
            logger.info("No customers found in dedicated sections, trying to extract from testimonials")
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
                        customer_data.append({
                            'name': name,
                            'url': None,
                            'source': "FeaturedCustomers - Testimonial"
                        })
                        logger.info(f"Found customer from testimonial: {name}",
                                  extra={'customer_name': name, 'source': 'testimonial'})
                        metrics['customers_found'] += 1
            
            metrics['extracted_from_testimonials'] = len(testimonials)
        
        # Final metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['customers_found'] = len(customer_data)
        metrics['status'] = 'success' if len(customer_data) > 0 else 'empty'
        log_data_metrics(logger, "featured_customers_scrape", metrics)
        
        logger.info(f"Completed FeaturedCustomers scraping for {vendor_name}. Found {len(customer_data)} customers.",
                  extra={'vendor_name': vendor_name, 'customer_count': len(customer_data)})
        
        return customer_data
    
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
        
        return []
