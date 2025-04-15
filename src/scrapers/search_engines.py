import requests
import logging
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import os

logger = logging.getLogger(__name__)

def search_google(vendor_name):
    """Search Google for customer information."""
    try:
        # Get API key and CX from environment
        api_key = os.environ.get('GOOGLE_API_KEY')
        cx = os.environ.get('GOOGLE_CX')
        
        if not api_key or not cx:
            logger.warning("Google API key or CX not found in environment variables, using limited search")
            return basic_search(vendor_name)
        
        # Define search queries
        queries = [
            f'"{vendor_name} customers"',
            f'"has chosen {vendor_name}"',
            f'"{vendor_name} case study"',
            f'"{vendor_name} success story"'
        ]
        
        all_results = []
        
        for query in queries:
            logger.info(f"Searching Google for: {query}")
            
            # Call Google Search API
            search_results = google_search(query)
            
            # Process results
            for result in search_results:
                title = result.get("title", "")
                snippet = result.get("snippet", "")
                link = result.get("link", "")
                
                # Skip results from the vendor's own website
                parsed_url = urlparse(link)
                if vendor_name.lower().replace(" ", "") in parsed_url.netloc:
                    continue
                
                # Extract potential customer name (this is a simplified approach)
                if "case study" in title.lower() or "success story" in title.lower():
                    parts = title.split("-")
                    if len(parts) > 1:
                        potential_customer = parts[0].strip()
                        if potential_customer and potential_customer.lower() != vendor_name.lower():
                            all_results.append({
                                "name": potential_customer,
                                "url": parsed_url.netloc if parsed_url.netloc else None,
                                "source": "Google Search"
                            })
                            logger.info(f"Found potential customer from Google: {potential_customer}")
        
        return all_results
    
    except Exception as e:
        logger.error(f"Error searching Google for {vendor_name}: {str(e)}")
        return []

def google_search(query: str) -> list:
    """Call Google Custom Search API."""
    try:
        api_key = os.environ.get('GOOGLE_API_KEY')
        cx = os.environ.get('GOOGLE_CX')
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": api_key,
            "cx": cx,
            "q": query
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json().get("items", [])
    except Exception as e:
        logger.error(f"Error in Google search API call: {str(e)}")
        return []

def basic_search(vendor_name):
    """Basic search function without using Google API."""
    # This is a placeholder function for when Google API key is not available
    # In a real application, you would implement a different search strategy
    logger.warning("Using basic search function - limited results")
    
    return [{
        "name": "Example Customer",
        "url": "example.com",
        "source": "Basic Search (Placeholder)"
    }]