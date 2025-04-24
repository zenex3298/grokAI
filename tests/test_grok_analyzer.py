#!/usr/bin/env python3
import os
import json
import logging
import sys
import requests
import time
from bs4 import BeautifulSoup
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

# Import utility for extracting text from HTML
def extract_text_from_html(html_content):
    """Extract clean text from HTML content."""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove script, style, and other non-content tags
    for script in soup(["script", "style", "meta", "link", "noscript", "svg", "path"]):
        script.extract()
    
    # Get text
    text = soup.get_text(separator=' ', strip=True)
    
    # Normalize whitespace
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = '\n'.join(chunk for chunk in chunks if chunk)
    
    return text

def extract_companies_with_grok(text_content, page_url, vendor_name, debug_mode=False):
    """Use Grok to extract company names from page text.
    
    Args:
        text_content: The text content to analyze
        page_url: The URL of the page
        vendor_name: The name of the vendor
        debug_mode: If True, prints extra debug information
    """
    # Get API key
    api_key = os.environ.get('GROK_API_KEY')
    
    if not api_key:
        print("GROK_API_KEY not found in environment variables")
        return []
    
    # Truncate text if too long
    if len(text_content) > 8000:
        print(f"Truncating page content from {len(text_content)} to 8000 chars")
        text_content = text_content[:8000]
    
    # Create prompt for Grok
    prompt = f"""
    Extract all company names that are customers or clients of {vendor_name} from this webpage content.
    The page URL is {page_url}.
    
    Here is the page content:
    {text_content}
    
    TASK: Thoroughly analyze this text and identify ALL company names that appear to be customers or clients of {vendor_name}.
    
    IMPORTANT: Take your time to analyze the entire content. You MUST spend at least 45-60 seconds analyzing the text.
    Look for sections with testimonials, case studies, customer logos, "trusted by" sections, and success stories.
    Companies are often mentioned in contexts like "X uses {vendor_name}", "Y chose {vendor_name}", etc.
    
    Look for these specific sections:
    - Customer stories/testimonials
    - "Trusted by" or "Our customers" sections
    - Case studies
    - Logos of companies displayed on the page
    - Reviews or ratings from companies
    
    Please respond with a JSON array of objects. Each object should have:
    1. "company_name": The name of the customer company
    2. "confidence": A number from 0 to 1 indicating how confident you are that this is a customer
    3. "reason": A brief explanation of why you think this is a customer

    Only include companies that you believe are actual customers with at least 60% confidence.
    Do not include {vendor_name} itself or generic terms.
    
    IMPORTANT: Only return up to 10 of the companies you are MOST confident about. Quality over quantity.
    
    You MUST take at least 45-60 seconds to thoroughly process this content before responding.
    Provide a thorough analysis as your response is critical for business intelligence.
    """
    
    # Call Grok API
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'VendorCustomerIntelligenceTool/1.0',
        'X-Request-ID': f'{vendor_name}-{int(time.time())}'
    }
    
    api_payload = {
        'model': 'grok-3-latest',
        'messages': [
            {'role': 'system', 'content': 'You are a helpful assistant that extracts company names from webpage content.'},
            {'role': 'user', 'content': prompt}
        ],
        'max_tokens': 2000,        # Increase max tokens to allow for longer responses
        'temperature': 0,
        'timeout': 50              # Add explicit timeout parameter for the model
    }
    
    try:
        # Create logs directory if it doesn't exist
        logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)
            print(f"Created logs directory: {logs_dir}")
        
        # Save prompt to a file for debugging
        prompt_file = os.path.join(logs_dir, f"grok_prompt_{int(time.time())}.txt")
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt)
        print(f"Saved Grok prompt to {prompt_file}")
        
        # Print preview of what's being sent to Grok
        print("\nPrompt preview (first 500 chars of user message):")
        print("-" * 50)
        print(prompt[:500] + "...")
        print("-" * 50)
        
        print(f"Sending page content from {page_url} to Grok API for company extraction")
        print(f"Start time: {datetime.now()}")
        
        response = requests.post(
            'https://api.x.ai/v1/chat/completions',
            headers=headers,
            timeout=60,  # 60 second timeout for HTTP request
            json=api_payload
        )
        
        print(f"Response received time: {datetime.now()}")
        
        if response.status_code != 200:
            print(f"Grok API error: {response.status_code}")
            return []
        
        grok_response = response.json()
        generated_text = grok_response.get('choices', [{}])[0].get('message', {}).get('content', '')
        
        print(f"Raw response from Grok ({len(generated_text)} chars):")
        print("-" * 40)
        print(generated_text[:1000] + ("..." if len(generated_text) > 1000 else ""))
        print("-" * 40)
        
        # Parse the JSON response
        try:
            # Try to extract just the JSON part if there's any surrounding text
            json_start = generated_text.find('[')
            json_end = generated_text.rfind(']') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = generated_text[json_start:json_end]
                print(f"Extracted JSON: {json_str[:500]}...")
                companies_data = json.loads(json_str)
            else:
                # If we can't find brackets, try parsing the whole response
                companies_data = json.loads(generated_text)
                
            if debug_mode:
                print(f"\nFound {len(companies_data)} raw company entries from Grok")
                
            # Format the extracted companies
            companies = []
            for company in companies_data:
                if isinstance(company, dict) and 'company_name' in company:
                    name = company['company_name']
                    confidence = company.get('confidence', 0.7)  # Default confidence
                    reason = company.get('reason', 'Extracted from page content')  # Get reason if available
                    
                    if confidence >= 0.6:  # Only include companies with sufficient confidence
                        # Generate domain from company name
                        domain = name.lower().replace(' ', '') + ".com"
                        
                        companies.append({
                            'name': name,
                            'url': domain,
                            'source': f"Grok extraction from {page_url}",
                            'confidence': confidence,
                            'reason': reason
                        })
            
            print(f"Grok extracted {len(companies)} companies from {page_url}")
            
            if debug_mode and len(companies) > 0:
                print("\nTop companies by confidence:")
                # Sort by confidence and take top 3 for quick preview
                top_companies = sorted(companies, key=lambda x: x.get('confidence', 0), reverse=True)[:3]
                for i, company in enumerate(top_companies, 1):
                    confidence = company.get('confidence', 'N/A')
                    confidence_str = f"{confidence:.2f}" if isinstance(confidence, float) else confidence
                    print(f"  {i}. {company['name']} (Confidence: {confidence_str})")
            
            return companies
            
        except json.JSONDecodeError as e:
            print(f"Failed to parse Grok response as JSON: {e}")
            print(f"Grok response content: {generated_text[:200]}...")
            return []
            
    except Exception as e:
        print(f"Error calling Grok API: {str(e)}")
        return []

def main():
    # Ensure API key is set
    grok_api_key = os.environ.get('GROK_API_KEY')
    if not grok_api_key:
        print("GROK_API_KEY environment variable must be set")
        sys.exit(1)
    else:
        print(f"Using GROK_API_KEY: {grok_api_key[:5]}...{grok_api_key[-5:]}")
        
    # Get limit argument if provided
    debug_limit = 5  # Default limit for debugging
    
    # Get URL from command line
    if len(sys.argv) < 2:
        print("Usage: python test_grok_analyzer.py <URL> [vendor_name] [limit]")
        print("  limit: Optional - number of results to display (default: 5)")
        sys.exit(1)
    
    url = sys.argv[1]
    vendor_name = sys.argv[2] if len(sys.argv) > 2 else "Company"
    
    # Check if limit is provided as the third argument
    if len(sys.argv) > 3:
        try:
            debug_limit = int(sys.argv[3])
            print(f"Result limit set to: {debug_limit}")
        except ValueError:
            print(f"Invalid limit value: {sys.argv[3]}. Using default: {debug_limit}")
    else:
        print(f"Using default result limit: {debug_limit}")
    
    print(f"\nAnalyzing URL: {url}")
    print(f"Vendor name: {vendor_name}")
    print(f"Start time: {datetime.now()}\n")
    
    try:
        # Fetch the webpage
        print(f"Fetching content from {url}")
        response = requests.get(url, timeout=15)
        
        if response.status_code != 200:
            print(f"Failed to fetch {url}, status code: {response.status_code}")
            sys.exit(1)
        
        # Extract text from HTML
        print(f"Parsing HTML content ({len(response.text)} bytes)")
        text_content = extract_text_from_html(response.text)
        print(f"Extracted {len(text_content)} characters of text")
        
        # Create logs directory if it doesn't exist
        logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)
            print(f"Created logs directory: {logs_dir}")
            
        # Save extracted content to file for inspection
        extracted_file = os.path.join(logs_dir, f"extracted_content_{int(time.time())}.txt")
        with open(extracted_file, "w", encoding="utf-8") as f:
            f.write(text_content)
        print(f"Saved extracted content to {extracted_file}")
        
        # Print a preview of the extracted content
        print("\nPreview of extracted content (first 500 chars):")
        print("-" * 50)
        print(text_content[:500] + "...")
        print("-" * 50)
        
        # Process with Grok
        # Pass True for debug_mode to enable extra debug output
        results = extract_companies_with_grok(text_content, url, vendor_name, debug_mode=True)
        
        # Display limited results
        print("\nResults:")
        print("-" * 50)
        if results:
            print(f"Found {len(results)} companies, displaying top {min(debug_limit, len(results))} by confidence:")
            
            # Sort by confidence and take top N
            sorted_results = sorted(results, key=lambda x: x.get('confidence', 0), reverse=True)
            limited_results = sorted_results[:debug_limit]
            
            for i, company in enumerate(limited_results, 1):
                confidence = company.get('confidence', 'N/A')
                confidence_str = f"{confidence:.2f}" if isinstance(confidence, float) else confidence
                reason = company.get('reason', 'No reason provided')
                
                print(f"{i}. {company['name']} (Confidence: {confidence_str})")
                print(f"   Reason: {reason}")
                print(f"   URL: {company.get('url', 'N/A')}")
                print()
        else:
            print("No companies found")
        
        print("-" * 50)
        print(f"Analysis completed at {datetime.now()}")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()