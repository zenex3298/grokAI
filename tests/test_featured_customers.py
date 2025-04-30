#!/usr/bin/env python3
import os
import sys
import logging
import time
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Add the project root to Python path so imports work
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables from .env file
def load_env_file():
    """Load environment variables from .env file."""
    # Try to find .env in current directory first
    env_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'),          # In tests dir
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')  # In project root
    ]
    
    env_loaded = False
    
    for env_path in env_paths:
        if os.path.exists(env_path):
            print(f"Loading environment from {env_path}")
            with open(env_path, 'r') as file:
                for line in file:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        os.environ[key.strip()] = value.strip().strip("'").strip('"')
            print("Environment variables loaded from .env file")
            env_loaded = True
            break
    
    if not env_loaded:
        print("WARNING: .env file not found in any expected location, using existing environment variables")

# Load environment variables
load_env_file()

# Import scrapers
from src.scrapers.featured_customers import scrape_featured_customers

def status_callback(metrics):
    """Callback function for status updates."""
    status = metrics.get('status', '')
    if status == 'featured_customers_started':
        print(f"Starting FeaturedCustomers search...")
    elif status == 'featured_customers_searching':
        print(f"Searching FeaturedCustomers...")
    elif status == 'featured_customers_parsing_search':
        print(f"Parsing FeaturedCustomers search results...")
    elif status == 'featured_customers_accessing_profile':
        print(f"Accessing vendor profile: {metrics.get('profile_url', '')}")
    elif status == 'featured_customers_parsing_profile':
        print(f"Analyzing vendor profile...")
    elif status == 'featured_customers_processing_section':
        section_index = metrics.get('current_section', 0)
        total_sections = metrics.get('total_sections', 0)
        print(f"Processing customer section {section_index}/{total_sections}...")
    elif status == 'featured_customers_found':
        print(f"Found {metrics.get('customers_found', 0)} customers so far...")
    elif status == 'complete':
        print(f"Search complete! Found {metrics.get('customers_found', 0)} customers.")
    elif status == 'error' or status.startswith('error'):
        print(f"Error: {metrics.get('error_message', 'Unknown error')}")
    else:
        print(f"Status update: {status}")

def main():
    # Get vendor name from command line
    if len(sys.argv) < 2:
        print("Usage: python test_featured_customers.py <vendor_name> [max_results]")
        print("  OR: python test_featured_customers.py --direct <vendor_profile_url> [max_results]")
        sys.exit(1)
    
    # Check for direct URL mode
    direct_mode = False
    if sys.argv[1] == "--direct" and len(sys.argv) > 2:
        direct_mode = True
        vendor_url = sys.argv[2]
        vendor_name = vendor_url.split("/")[-1] if "/" in vendor_url else "Unknown"
        max_results = 20
        
        # Check if max_results is provided as the third argument
        if len(sys.argv) > 3:
            try:
                max_results = int(sys.argv[3])
                print(f"Max results set to: {max_results}")
            except ValueError:
                print(f"Invalid max_results value: {sys.argv[3]}. Using default: {max_results}")
        else:
            print(f"Using default max_results: {max_results}")
            
        print(f"\nDirectly accessing FeaturedCustomers profile URL: {vendor_url}")
    else:
        vendor_name = sys.argv[1]
        max_results = 20
        
        # Check if max_results is provided as the second argument
        if len(sys.argv) > 2:
            try:
                max_results = int(sys.argv[2])
                print(f"Max results set to: {max_results}")
            except ValueError:
                print(f"Invalid max_results value: {sys.argv[2]}. Using default: {max_results}")
        else:
            print(f"Using default max_results: {max_results}")
        
        print(f"\nSearching FeaturedCustomers for vendor: {vendor_name}")
    
    print(f"Start time: {datetime.now()}\n")
    
    try:
        # Run the featured customers search
        start_time = time.time()
        
        if direct_mode:
            # For direct mode, we need to modify the scrape_featured_customers function
            # Here we'll implement a minimal version of the functionality
            import requests
            from bs4 import BeautifulSoup
            
            print(f"Directly accessing vendor profile at: {vendor_url}")
            
            # Make request to the profile page
            try:
                response = requests.get(vendor_url, timeout=10)
                if response.status_code != 200:
                    print(f"Failed to access profile, status code: {response.status_code}")
                    sys.exit(1)
                    
                print(f"Successfully loaded profile page ({len(response.text)} bytes)")
                
                # Parse HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Look for customer sections
                print("Searching for customer sections in profile")
                customer_sections = soup.find_all(['div', 'section'], 
                                               class_=lambda c: c and 'customer' in str(c).lower())
                
                print(f"Found {len(customer_sections)} customer sections")
                
                # If no explicit customer sections, try alternative sections
                if len(customer_sections) == 0:
                    alt_sections = soup.find_all(['div', 'section'], 
                                              class_=lambda c: c and any(term in str(c).lower() 
                                                                       for term in ['testimonial', 'case-study', 
                                                                                   'success-story']))
                    
                    if alt_sections:
                        print(f"No customer sections found, but found {len(alt_sections)} alternative sections")
                        customer_sections = alt_sections
                
                # Extract customer data
                customer_data = []
                
                # Process each section
                for i, section in enumerate(customer_sections):
                    print(f"Processing customer section {i+1}/{len(customer_sections)}")
                    
                    # Extract customer names
                    customer_elems = section.find_all(['h3', 'h4', 'div', 'span'], 
                                                   class_=lambda c: c and 'name' in str(c).lower())
                    
                    print(f"Found {len(customer_elems)} potential customer elements in section {i+1}")
                    
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
                                    print(f"Found URL for customer {name}: {url}")
                            
                            customer_data.append({
                                'name': name,
                                'url': url,
                                'source': "FeaturedCustomers (Direct)"
                            })
                            print(f"Found customer: {name}")
                            
                            # Check if we've reached the max_results
                            if len(customer_data) >= max_results:
                                print(f"Reached maximum result count ({max_results}), stopping search")
                                break
                    
                    # Check if we've reached the max_results
                    if len(customer_data) >= max_results:
                        break
                
                # If no customers found via specific sections, try testimonials
                if len(customer_data) == 0:
                    print("No customers found in dedicated sections, trying to extract from testimonials")
                    testimonials = soup.find_all(['div', 'blockquote'], 
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
                                    url = link['href']
                                
                                customer_data.append({
                                    'name': name,
                                    'url': url,
                                    'source': "FeaturedCustomers - Testimonial (Direct)"
                                })
                                print(f"Found customer from testimonial: {name}")
                                
                                # Check if we've reached the max_results
                                if len(customer_data) >= max_results:
                                    print(f"Reached maximum result count ({max_results}), stopping search")
                                    break
                
                results = customer_data
                
            except Exception as e:
                print(f"Error in direct access mode: {str(e)}")
                sys.exit(1)
        else:
            # Use the regular scraper function
            results = scrape_featured_customers(vendor_name, max_results=max_results, status_callback=status_callback)
        
        end_time = time.time()
        
        # Display results
        print("\nResults:")
        print("-" * 50)
        if results:
            print(f"Found {len(results)} customers on FeaturedCustomers:")
            
            for i, customer in enumerate(results, 1):
                print(f"{i}. {customer['name']}")
                print(f"   URL: {customer.get('url', 'N/A')}")
                print(f"   Source: {customer.get('source', 'N/A')}")
                print()
        else:
            print("No customers found on FeaturedCustomers")
        
        print("-" * 50)
        print(f"Search completed in {end_time - start_time:.2f} seconds")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()