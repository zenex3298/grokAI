import os
import sys
import time
import json
from dotenv import load_dotenv

# Add the parent directory to sys.path to allow importing from the package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.scrapers.builtwith import scrape_builtwith
from src.utils.logger import setup_logging

# Load environment variables from .env file
load_dotenv()

# Setup logging
logger = setup_logging()

def print_progress(metrics):
    """Simple callback function to print progress updates."""
    status = metrics.get('status', '')
    if status == 'builtwith_customer_found':
        print(f"Found {metrics.get('customers_found', 0)} customers so far...")
    elif status == 'builtwith_searching':
        print(f"Searching BuiltWith for {metrics.get('vendor_name', '')}...")
    elif status == 'builtwith_parsing_search':
        print(f"Parsing search results...")
    elif status == 'builtwith_analyzing':
        print(f"Analyzing content...")
    elif status == 'complete':
        print(f"BuiltWith search complete! Found {metrics.get('customers_found', 0)} customers.")
    elif status == 'error' or status == 'failed':
        print(f"Error: {metrics.get('error_message', metrics.get('failure_reason', 'Unknown error'))}")

def test_builtwith_scraper():
    """Test the BuiltWith scraper functionality."""
    print("Testing BuiltWith scraper...")
    
    # Use a well-known vendor for testing
    vendor_name = "Salesforce"
    max_results = 10  # Limit results for testing
    
    # Run the scraper with progress callback
    results = scrape_builtwith(vendor_name, max_results=max_results, status_callback=print_progress)
    
    # Display results
    print(f"\nFound {len(results)} customers for {vendor_name}:")
    
    for i, item in enumerate(results, 1):
        print(f"{i}. {item.get('name', 'Unknown')} - {item.get('url', 'No URL')}")
    
    # Save results to JSON file for inspection
    output_file = f"builtwith_results_{int(time.time())}.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to {output_file}")

if __name__ == "__main__":
    test_builtwith_scraper()