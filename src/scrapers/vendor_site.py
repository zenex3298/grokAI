import requests
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

def get_domain_from_name(vendor_name):
    """Attempt to generate a domain from vendor name."""
    # Simple conversion - replace spaces with empty string and add .com
    # In a real application, you would have more sophisticated logic
    domain = vendor_name.lower().replace(' ', '')
    return f"https://www.{domain}.com"

def scrape_vendor_site(vendor_name):
    """Scrape vendor website for customer information."""
    try:
        # Generate domain from vendor name
        domain = get_domain_from_name(vendor_name)
        logger.info(f"Generated domain: {domain}")
        
        # Make request to vendor site
        response = requests.get(domain, timeout=10)
        if response.status_code != 200:
            logger.warning(f"Failed to access {domain}, status code: {response.status_code}")
            return []
        
        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for customer pages
        customer_data = []
        
        # Check for common customer page links
        customer_pages = ['customers', 'case-studies', 'success-stories', 'clients']
        for page in customer_pages:
            for link in soup.find_all('a', href=True):
                if page in link['href'].lower():
                    customer_page_url = urljoin(domain, link['href'])
                    logger.info(f"Found potential customer page: {customer_page_url}")
                    customer_data.extend(scrape_customer_page(customer_page_url))
        
        # Look for logo sections on main page
        logo_sections = soup.find_all(['div', 'section', 'ul'], 
                                     class_=lambda c: c and any(term in c.lower() 
                                                              for term in ['logo', 'client', 'customer', 'partner']))
        
        for section in logo_sections:
            # Extract company names from alt text in images
            for img in section.find_all('img', alt=True):
                alt_text = img['alt']
                if alt_text and len(alt_text) > 2:  # Basic filtering
                    customer_data.append({
                        'name': alt_text.strip(),
                        'url': None,  # Would need additional logic to determine URL
                        'source': f"{vendor_name} website - logo section"
                    })
                    logger.info(f"Found potential customer from logo: {alt_text.strip()}")
        
        return customer_data
    
    except Exception as e:
        logger.error(f"Error scraping vendor site {vendor_name}: {str(e)}")
        return []

def scrape_customer_page(url):
    """Scrape a customer or case studies page."""
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        customer_data = []
        
        # Look for customer names in headings
        for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            text = heading.get_text().strip()
            if text and len(text) > 2 and 'case study' in text.lower():
                # Extract company name (this is a simplified approach)
                company_name = text.split('Case Study')[0].strip()
                if company_name:
                    customer_data.append({
                        'name': company_name,
                        'url': None,
                        'source': f"Case study page - {url}"
                    })
                    logger.info(f"Found potential customer from case study: {company_name}")
        
        # Look for logos or customer cards
        customer_sections = soup.find_all(['div', 'section', 'article'], 
                                         class_=lambda c: c and any(term in str(c).lower() 
                                                                  for term in ['customer', 'client', 'logo', 'case']))
        
        for section in customer_sections:
            # Extract from headings within sections
            for heading in section.find_all(['h2', 'h3', 'h4']):
                text = heading.get_text().strip()
                if text and len(text) > 2:
                    customer_data.append({
                        'name': text,
                        'url': None,
                        'source': f"Customer section - {url}"
                    })
                    logger.info(f"Found potential customer from section: {text}")
        
        return customer_data
    
    except Exception as e:
        logger.error(f"Error scraping customer page {url}: {str(e)}")
        return []
