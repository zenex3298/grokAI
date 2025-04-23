import requests
import time
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin, urlparse

from src.utils.logger import get_logger, LogComponent, set_context, log_data_metrics, log_function_call

# Get a logger specifically for the vendor site component
logger = get_logger(LogComponent.VENDOR_SITE)

def get_domain_from_name(vendor_name):
    """Attempt to generate a domain from vendor name."""
    # Simple conversion - replace spaces with empty string and add .com
    # In a real application, you would have more sophisticated logic
    domain = vendor_name.lower().replace(' ', '')
    return f"https://www.{domain}.com"

@log_function_call
def scrape_vendor_site(vendor_name):
    """Scrape vendor website for customer information."""
    # Set the context for this operation
    set_context(vendor_name=vendor_name, operation="vendor_site_scrape")
    
    # Initialize metrics
    metrics = {
        'start_time': time.time(),
        'vendor_name': vendor_name,
        'pages_checked': 0,
        'pages_found': 0,
        'logo_sections_found': 0,
        'customer_links_found': 0,
        'customers_found': 0,
        'status': 'started'
    }
    
    try:
        logger.info(f"Starting vendor site scraping for: {vendor_name}")
        
        # Generate domain from vendor name
        domain = get_domain_from_name(vendor_name)
        logger.info(f"Generated domain: {domain}", extra={'domain': domain})
        
        # Make request to vendor site
        start_req = time.time()
        logger.debug(f"Making HTTP request to vendor site: {domain}")
        
        try:
            response = requests.get(domain, timeout=10)
            metrics['main_page_status'] = response.status_code
            metrics['main_page_load_time'] = time.time() - start_req
            
            if response.status_code != 200:
                logger.warning(f"Failed to access {domain}, status code: {response.status_code}", 
                              extra={'status_code': response.status_code, 'url': domain})
                metrics['status'] = 'failed'
                metrics['failure_reason'] = f"HTTP {response.status_code}"
                log_data_metrics(logger, "vendor_site_scrape", metrics)
                return []
                
            logger.info(f"Successfully loaded vendor site: {domain} ({len(response.text)} bytes)", 
                       extra={'response_size': len(response.text)})
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error accessing {domain}: {str(e)}", 
                        extra={'error_type': type(e).__name__, 'url': domain})
            metrics['status'] = 'failed'
            metrics['failure_reason'] = f"Request error: {type(e).__name__}"
            log_data_metrics(logger, "vendor_site_scrape", metrics)
            return []
        
        # Parse HTML
        logger.debug(f"Parsing HTML content from {domain}")
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for customer pages
        customer_data = []
        metrics['pages_checked'] += 1
        
        # Check for common customer page links
        customer_pages = ['customers', 'case-studies', 'success-stories', 'clients', 'testimonials']
        logger.info(f"Searching for customer pages with keywords: {', '.join(customer_pages)}")
        
        customer_page_links = []
        for page in customer_pages:
            for link in soup.find_all('a', href=True):
                if page in link['href'].lower():
                    customer_page_url = urljoin(domain, link['href'])
                    customer_page_links.append(customer_page_url)
                    logger.info(f"Found potential customer page: {customer_page_url}", 
                              extra={'page_type': page, 'url': customer_page_url})
                    metrics['customer_links_found'] += 1
        
        # Remove duplicate URLs
        customer_page_links = list(set(customer_page_links))
        metrics['unique_customer_pages'] = len(customer_page_links)
        
        # Scrape each customer page
        for page_url in customer_page_links:
            logger.info(f"Scraping customer page: {page_url}")
            page_customers = scrape_customer_page(page_url)
            customer_data.extend(page_customers)
            metrics['pages_found'] += 1
            metrics['customers_found'] += len(page_customers)
            
            logger.info(f"Found {len(page_customers)} potential customers on page {page_url}", 
                       extra={'count': len(page_customers), 'url': page_url})
        
        # Look for logo sections on main page
        logger.info("Searching for logo sections on main page")
        logo_section_keywords = ['logo', 'client', 'customer', 'partner', 'trust']
        
        logo_sections = soup.find_all(['div', 'section', 'ul'], 
                                    class_=lambda c: c and any(term in str(c).lower() 
                                                             for term in logo_section_keywords))
        
        metrics['logo_sections_found'] = len(logo_sections)
        logger.info(f"Found {len(logo_sections)} potential logo sections", 
                  extra={'count': len(logo_sections)})
        
        for i, section in enumerate(logo_sections):
            section_id = section.get('id', f'section_{i}')
            section_class = section.get('class', ['unknown'])
            logger.debug(f"Processing logo section {i+1}/{len(logo_sections)}: {section_id} {section_class}")
            
            # Count total images in section
            all_images = section.find_all('img')
            images_with_alt = [img for img in all_images if img.get('alt')]
            
            logger.debug(f"Logo section {i+1} has {len(all_images)} images, {len(images_with_alt)} with alt text",
                       extra={'section_index': i, 'total_images': len(all_images), 
                              'images_with_alt': len(images_with_alt)})
            
            # Extract company names from alt text in images
            for img in section.find_all('img', alt=True):
                alt_text = img['alt'].strip()
                if alt_text and len(alt_text) > 2:  # Basic filtering
                    # Check if it's a likely customer name and not just "logo" or similar generic text
                    if not any(term.lower() in alt_text.lower() for term in ['logo', 'icon', 'image']):
                        customer_data.append({
                            'name': alt_text,
                            'url': None,  # Would need additional logic to determine URL
                            'source': f"{vendor_name} website - logo section"
                        })
                        logger.info(f"Found potential customer from logo: {alt_text}", 
                                  extra={'customer_name': alt_text, 'source': 'logo_section'})
                        metrics['customers_found'] += 1
        
        # Deduplicate customers by name
        unique_customers = {}
        for customer in customer_data:
            name = customer['name'].lower()
            if name not in unique_customers:
                unique_customers[name] = customer
        
        deduplicated_data = list(unique_customers.values())
        metrics['unique_customers'] = len(deduplicated_data)
        
        # Log final metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'success'
        log_data_metrics(logger, "vendor_site_scrape", metrics)
        
        logger.info(f"Completed vendor site scraping for {vendor_name}. Found {len(deduplicated_data)} unique customers from {metrics['pages_found']} pages and {metrics['logo_sections_found']} logo sections.",
                   extra={'vendor_name': vendor_name, 'customers_found': len(deduplicated_data)})
        
        return deduplicated_data
    
    except Exception as e:
        logger.exception(f"Error scraping vendor site {vendor_name}: {str(e)}", 
                       extra={'error_type': type(e).__name__, 'error_message': str(e)})
        
        # Log failure metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'error'
        metrics['error_type'] = type(e).__name__
        metrics['error_message'] = str(e)
        log_data_metrics(logger, "vendor_site_scrape", metrics)
        
        return []

@log_function_call
def scrape_customer_page(url):
    """Scrape a customer or case studies page."""
    page_metrics = {
        'start_time': time.time(),
        'url': url,
        'headings_checked': 0,
        'sections_found': 0,
        'customers_found': 0,
        'status': 'started'
    }
    
    try:
        logger.debug(f"Starting to scrape customer page: {url}")
        start_req = time.time()
        
        try:
            response = requests.get(url, timeout=10)
            page_metrics['status_code'] = response.status_code
            page_metrics['load_time'] = time.time() - start_req
            
            if response.status_code != 200:
                logger.warning(f"Failed to access customer page {url}, status code: {response.status_code}",
                              extra={'url': url, 'status_code': response.status_code})
                page_metrics['status'] = 'failed'
                page_metrics['failure_reason'] = f"HTTP {response.status_code}"
                log_data_metrics(logger, "customer_page_scrape", page_metrics)
                return []
                
            logger.debug(f"Successfully loaded customer page: {url} ({len(response.text)} bytes)", 
                       extra={'url': url, 'response_size': len(response.text)})
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error accessing customer page {url}: {str(e)}", 
                        extra={'error_type': type(e).__name__, 'url': url})
            page_metrics['status'] = 'failed'
            page_metrics['failure_reason'] = f"Request error: {type(e).__name__}"
            log_data_metrics(logger, "customer_page_scrape", page_metrics)
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        customer_data = []
        
        # Look for customer names in headings
        logger.debug(f"Searching for case study headings in {url}")
        headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        page_metrics['headings_checked'] = len(headings)
        
        heading_keywords = ['case study', 'success story', 'customer success', 'client story']
        
        for heading in headings:
            text = heading.get_text().strip()
            if text and len(text) > 2:
                # Check if this is a case study heading
                if any(keyword in text.lower() for keyword in heading_keywords):
                    # Try to extract company name
                    for keyword in heading_keywords:
                        if keyword in text.lower():
                            company_name = text.split(keyword, 1)[0].strip()
                            break
                    else:
                        company_name = text
                    
                    if company_name and len(company_name) > 2:
                        customer_data.append({
                            'name': company_name,
                            'url': None,
                            'source': f"Case study page - {url}"
                        })
                        logger.info(f"Found potential customer from case study heading: {company_name}", 
                                  extra={'customer_name': company_name, 'source': 'case_study_heading', 'url': url})
                        page_metrics['customers_found'] += 1
        
        # Look for logos or customer cards
        logger.debug(f"Searching for customer sections in {url}")
        section_keywords = ['customer', 'client', 'logo', 'case', 'testimonial', 'success']
        
        customer_sections = soup.find_all(['div', 'section', 'article'], 
                                         class_=lambda c: c and any(term in str(c).lower() 
                                                                  for term in section_keywords))
        
        page_metrics['sections_found'] = len(customer_sections)
        logger.debug(f"Found {len(customer_sections)} potential customer sections in {url}",
                   extra={'url': url, 'section_count': len(customer_sections)})
        
        for i, section in enumerate(customer_sections):
            section_id = section.get('id', f'section_{i}')
            section_class = section.get('class', ['unknown'])
            logger.debug(f"Processing customer section {i+1}/{len(customer_sections)}: {section_id} {section_class}")
            
            # Extract from headings within sections
            section_headings = section.find_all(['h2', 'h3', 'h4'])
            
            for heading in section_headings:
                text = heading.get_text().strip()
                if text and len(text) > 2:
                    # Skip if it contains generic terms
                    if not any(term.lower() in text.lower() for term in ['our customers', 'testimonials', 'case studies']):
                        customer_data.append({
                            'name': text,
                            'url': None,
                            'source': f"Customer section - {url}"
                        })
                        logger.info(f"Found potential customer from section heading: {text}", 
                                  extra={'customer_name': text, 'source': 'section_heading', 'url': url})
                        page_metrics['customers_found'] += 1
            
            # Look for structured customer data
            customer_cards = section.find_all(['div', 'article'], 
                                             class_=lambda c: c and any(term in str(c).lower() 
                                                                       for term in ['customer', 'client', 'card', 'item']))
            
            for card in customer_cards:
                # Try to find customer name in card
                name_elem = card.find(['h3', 'h4', 'h5', 'strong', 'b'])
                if name_elem:
                    name = name_elem.get_text().strip()
                    if name and len(name) > 2:
                        # Check for a URL
                        url_elem = card.find('a', href=True)
                        customer_url = url_elem['href'] if url_elem else None
                        
                        customer_data.append({
                            'name': name,
                            'url': customer_url,
                            'source': f"Customer card - {url}"
                        })
                        logger.info(f"Found potential customer from card: {name}", 
                                  extra={'customer_name': name, 'source': 'customer_card', 'url': url})
                        page_metrics['customers_found'] += 1
        
        # Log completion metrics
        page_metrics['end_time'] = time.time()
        page_metrics['duration'] = page_metrics['end_time'] - page_metrics['start_time']
        page_metrics['status'] = 'success'
        page_metrics['customer_count'] = len(customer_data)
        log_data_metrics(logger, "customer_page_scrape", page_metrics)
        
        logger.info(f"Completed scraping customer page {url}. Found {len(customer_data)} potential customers.",
                   extra={'url': url, 'customers_found': len(customer_data)})
        
        return customer_data
    
    except Exception as e:
        logger.exception(f"Error scraping customer page {url}: {str(e)}", 
                        extra={'error_type': type(e).__name__, 'error_message': str(e), 'url': url})
        
        # Log failure metrics
        page_metrics['end_time'] = time.time()
        page_metrics['duration'] = page_metrics['end_time'] - page_metrics['start_time']
        page_metrics['status'] = 'error'
        page_metrics['error_type'] = type(e).__name__
        page_metrics['error_message'] = str(e)
        log_data_metrics(logger, "customer_page_scrape", page_metrics)
        
        return []
