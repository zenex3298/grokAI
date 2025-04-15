import requests
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def scrape_featured_customers(vendor_name):
    """Scrape FeaturedCustomers.com for information about the vendor's customers."""
    try:
        # Create a search URL for Featured Customers
        search_url = f"https://www.featuredcustomers.com/search?q={vendor_name.replace(' ', '+')}" 
        
        logger.info(f"Searching FeaturedCustomers at: {search_url}")
        
        # Make request
        response = requests.get(search_url, timeout=10)
        if response.status_code != 200:
            logger.warning(f"Failed to access FeaturedCustomers, status code: {response.status_code}")
            return []
        
        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find vendor profile link (if exists)
        vendor_profile = None
        for link in soup.find_all('a', href=True):
            if f"/vendor/{vendor_name.lower().replace(' ', '-')}" in link['href'] or \
               vendor_name.lower() in link.get_text().lower():
                vendor_profile = f"https://www.featuredcustomers.com{link['href']}"
                logger.info(f"Found vendor profile: {vendor_profile}")
                break
        
        if not vendor_profile:
            logger.info(f"No vendor profile found for {vendor_name} on FeaturedCustomers")
            return []
        
        # Access vendor profile
        profile_response = requests.get(vendor_profile, timeout=10)
        if profile_response.status_code != 200:
            return []
        
        profile_soup = BeautifulSoup(profile_response.text, 'html.parser')
        
        # Look for customer section
        customer_data = []
        customer_sections = profile_soup.find_all(['div', 'section'], 
                                                class_=lambda c: c and 'customer' in str(c).lower())
        
        for section in customer_sections:
            # Extract customer names
            for customer_elem in section.find_all(['h3', 'h4', 'div', 'span'], 
                                                class_=lambda c: c and 'name' in str(c).lower()):
                name = customer_elem.get_text().strip()
                if name and len(name) > 2:
                    # Try to find associated URL
                    url = None
                    parent = customer_elem.parent
                    if parent:
                        link = parent.find('a', href=True)
                        if link and 'http' in link['href']:
                            url = link['href']
                    
                    customer_data.append({
                        'name': name,
                        'url': url,
                        'source': "FeaturedCustomers"
                    })
                    logger.info(f"Found customer from FeaturedCustomers: {name}")
        
        return customer_data
    
    except Exception as e:
        logger.error(f"Error scraping FeaturedCustomers for {vendor_name}: {str(e)}")
        return []
