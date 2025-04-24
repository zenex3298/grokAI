import os
import time
import requests
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from src.utils.logger import get_logger, LogComponent, set_context, log_data_metrics, log_function_call

# Get a logger specifically for the enhanced search component
logger = get_logger(LogComponent.SCRAPER)

def get_domain_from_name(vendor_name):
    """Attempt to generate a domain from vendor name."""
    # Simple conversion - replace spaces with empty string and add .com
    domain = vendor_name.lower().replace(' ', '')
    return f"https://www.{domain}.com"

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

def extract_companies_with_grok(text_content, page_url, vendor_name):
    """Use Grok to extract company names from page text."""
    # Get API key
    api_key = os.environ.get('GROK_API_KEY')
    
    if not api_key:
        logger.error("GROK_API_KEY not found in environment variables")
        return []
    
    # Truncate text if too long, but try to keep a larger chunk than before
    max_chars = 12000  # Increased from 8000 to 12000
    if len(text_content) > max_chars:
        logger.info(f"Truncating page content from {len(text_content)} to {max_chars} chars")
        text_content = text_content[:max_chars]
    
    # Create enhanced prompt for Grok with specific filtering instructions
    prompt = f"""
    Extract all ACTUAL company names that are customers or clients of {vendor_name} from this webpage content.
    The page URL is {page_url}.
    
    Here is the page content:
    {text_content}
    
    TASK: Thoroughly analyze this text and identify ONLY legitimate company names that appear to be customers or clients of {vendor_name}.
    
    IMPORTANT: Take your time to analyze the entire content. You MUST spend at least 45-60 seconds analyzing the text.
    Look for sections with testimonials, case studies, customer logos, "trusted by" sections, and success stories.
    Companies are often mentioned in contexts like "X uses {vendor_name}", "Y chose {vendor_name}", etc.
    
    CRITICAL FILTERING INSTRUCTIONS:
    - DO NOT include navigation menu items, category names, or UI elements
    - DO NOT include generic headings like "Trusted by" or "Our Customers"
    - DO NOT include slogans, marketing copy, or promotional text
    - DO NOT include general phrases that aren't company names
    - DO NOT include descriptive sections like "Government and Public Sector"
    - A real company name typically includes terms like Inc, LLC, Ltd, GmbH, or has a distinctive brand name
    - Focus on names that have actual evidence of being customers in the text
    
    Look for these specific sections:
    - Customer stories/testimonials with REAL customer names
    - "Trusted by" sections that list ACTUAL company names
    - Case studies that mention SPECIFIC companies by name
    - Logos of identifiable companies displayed on the page
    - Reviews or ratings from named organizations
    
    Please respond with a JSON array of objects. Each object should have:
    1. "company_name": The name of the actual customer company
    2. "confidence": A number from 0 to 1 indicating how confident you are that this is a customer
    3. "reason": A brief explanation of why you think this is a customer

    ONLY include companies that you believe are actual customers with at least 80% confidence.
    Do not include {vendor_name} itself or generic terms.
    
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
        logger.info(f"Sending page content from {page_url} to Grok API for company extraction")
        # Increase timeout to give Grok more time to process large content
        response = requests.post(
            'https://api.x.ai/v1/chat/completions',
            headers=headers,
            timeout=60,  # Increase timeout from 30 to 60 seconds
            json=api_payload
        )
        
        if response.status_code != 200:
            logger.error(f"Grok API error: {response.status_code}")
            return []
        
        grok_response = response.json()
        generated_text = grok_response.get('choices', [{}])[0].get('message', {}).get('content', '')
        
        # Parse the JSON response
        try:
            # Log the response for debugging
            logger.debug(f"Grok response: {generated_text[:500]}...")
            
            # Try to extract just the JSON part if there's any surrounding text
            json_start = generated_text.find('[')
            json_end = generated_text.rfind(']') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = generated_text[json_start:json_end]
                logger.debug(f"Extracted JSON string: {json_str[:500]}...")
                companies_data = json.loads(json_str)
            else:
                # If we can't find brackets, try parsing the whole response
                companies_data = json.loads(generated_text)
                
            # Format the extracted companies
            companies = []
            for company in companies_data:
                if isinstance(company, dict) and 'company_name' in company:
                    name = company['company_name']
                    confidence = company.get('confidence', 0.7)  # Default confidence
                    reason = company.get('reason', 'Extracted from page content')  # Get reason if available
                    
                    if confidence >= 0.8:  # Increased threshold from 0.6 to 0.8 to reduce false positives
                        # Generate domain from company name
                        # Only use lowercase alphanumeric characters and strip punctuation
                        clean_name = ''.join(e.lower() for e in name if e.isalnum() or e.isspace())
                        domain = clean_name.replace(' ', '') + ".com"
                        
                        companies.append({
                            'name': name,
                            'url': domain,
                            'source': f"Grok extraction from {page_url}",
                            'confidence': confidence,
                            'reason': reason
                        })
            
            logger.info(f"Grok extracted {len(companies)} companies from {page_url}")
            return companies
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Grok response as JSON: {e}")
            logger.debug(f"Grok response content: {generated_text[:200]}...")
            return []
            
    except Exception as e:
        logger.error(f"Error calling Grok API: {str(e)}")
        return []

# Helper functions
def get_unique_companies(companies):
    """Get unique companies from list, keeping highest confidence entries."""
    unique_companies = {}
    for company in companies:
        name = company['name'].lower()
        # Keep the higher confidence entry if duplicate
        if name not in unique_companies or company.get('confidence', 0) > unique_companies[name].get('confidence', 0):
            unique_companies[name] = company
    
    return unique_companies

class SearchResults:
    """Class to hold search results and metrics."""
    def __init__(self, results, metrics):
        self.results = results
        self.metrics = metrics

def format_results(unique_companies_dict, vendor_name, metrics, max_results):
    """Format final results with metrics and return top companies by confidence."""
    # Convert dict to list
    if isinstance(unique_companies_dict, dict):
        all_deduplicated = list(unique_companies_dict.values())
    else:
        all_deduplicated = unique_companies_dict
        
    metrics['unique_companies'] = len(all_deduplicated)
    metrics['target_count'] = max_results  # Add target count to metrics
    
    # Sort by confidence and limit results
    if len(all_deduplicated) > max_results:
        logger.info(f"Limiting results from {len(all_deduplicated)} to {max_results}")
        # Sort by confidence (highest first)
        sorted_results = sorted(all_deduplicated, key=lambda x: x.get('confidence', 0), reverse=True)
        # Limit to max_results
        limited_results = sorted_results[:max_results]
        metrics['returned_companies'] = len(limited_results)
    else:
        limited_results = all_deduplicated
        metrics['returned_companies'] = len(limited_results)
    
    # Log final metrics
    metrics['end_time'] = time.time()
    metrics['duration'] = metrics['end_time'] - metrics['start_time']
    metrics['status'] = 'success'
    log_data_metrics(logger, "enhanced_vendor_search", metrics)
    
    logger.info(f"Completed enhanced vendor search for {vendor_name}. Found {len(all_deduplicated)} unique companies from {metrics['pages_checked']} pages. Returning top {len(limited_results)}.")
    
    # Return both results and metrics
    return SearchResults(limited_results, metrics)

@log_function_call
def enhanced_vendor_search(vendor_name, max_results=20, status_callback=None):
    """Search vendor site and extract companies using Grok AI.
    
    Args:
        vendor_name: Name of the vendor to search for
        max_results: Maximum number of results to return (default: 20)
        status_callback: Optional callback function to update processing status
                        Callback signature: func(metrics: dict) -> None
        
    NOTE: This function will stop processing as soon as max_results 
          companies are found, to improve performance.
    """
    # Set the context for this operation
    set_context(vendor_name=vendor_name, operation="enhanced_vendor_search")
    
    # Initialize metrics
    metrics = {
        'start_time': time.time(),
        'vendor_name': vendor_name,
        'pages_checked': 0,
        'customer_links_found': 0,
        'grok_api_calls': 0,
        'companies_found': 0,
        'target_count': max_results,
        'early_exit': False,
        'current_page': None,
        'status': 'started'
    }
    
    # Call status callback with initial metrics if provided
    if status_callback:
        status_callback(metrics.copy())
    
    try:
        logger.info(f"Starting enhanced vendor search for: {vendor_name}")
        metrics['status'] = 'generating_domain'
        
        # Generate domain from vendor name
        domain = get_domain_from_name(vendor_name)
        logger.info(f"Generated domain: {domain}")
        
        # Update metrics with current page
        metrics['current_page'] = domain
        metrics['status'] = 'accessing_vendor_site'
        
        # Call status callback if provided
        if status_callback:
            status_callback(metrics.copy())
        
        # Make request to vendor site
        try:
            logger.info(f"Making HTTP request to vendor site: {domain}")
            response = requests.get(domain, timeout=15)
            
            if response.status_code != 200:
                logger.warning(f"Failed to access {domain}, status code: {response.status_code}")
                metrics['status'] = 'failed'
                metrics['failure_reason'] = f"HTTP {response.status_code}"
                log_data_metrics(logger, "enhanced_vendor_search", metrics)
                
                # Notify about failure via callback
                if status_callback:
                    status_callback(metrics.copy())
                    
                return []
                
            logger.info(f"Successfully loaded vendor site: {domain} ({len(response.text)} bytes)")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error accessing {domain}: {str(e)}")
            metrics['status'] = 'failed'
            metrics['failure_reason'] = f"Request error: {type(e).__name__}"
            log_data_metrics(logger, "enhanced_vendor_search", metrics)
            
            # Notify about failure via callback
            if status_callback:
                status_callback(metrics.copy())
                
            return []
        
        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Store all found customers
        all_customers = []
        metrics['pages_checked'] += 1
        metrics['status'] = 'finding_customer_pages'
        
        # Update status via callback
        if status_callback:
            status_callback(metrics.copy())
        
        # Look for customer pages
        customer_pages = ['customers', 'case-studies', 'success-stories', 'success', 'stories', 'clients', 'testimonials', 'review', 'reviews']
        logger.info(f"Searching for customer pages with keywords: {', '.join(customer_pages)}")
        
        customer_page_links = []
        for page in customer_pages:
            for link in soup.find_all('a', href=True):
                if page in link['href'].lower():
                    customer_page_url = urljoin(domain, link['href'])
                    customer_page_links.append(customer_page_url)
                    logger.info(f"Found potential customer page: {customer_page_url}")
                    metrics['customer_links_found'] += 1
        
        # Remove duplicate URLs
        customer_page_links = list(set(customer_page_links))
        metrics['unique_customer_pages'] = len(customer_page_links)
        
        # Update status after finding customer pages
        metrics['status'] = 'analyzing_main_page'
        if status_callback:
            status_callback(metrics.copy())
        
        # First analyze the main page with Grok
        logger.info(f"Analyzing main page content with Grok: {domain}")
        main_page_text = extract_text_from_html(response.text)
        main_page_customers = extract_companies_with_grok(main_page_text, domain, vendor_name)
        metrics['grok_api_calls'] += 1
        
        all_customers.extend(main_page_customers)
        metrics['companies_found'] += len(main_page_customers)
        
        # Update status after analyzing main page and update results
        metrics['status'] = 'processing_main_page_results'
        if status_callback:
            status_callback(metrics.copy())
        
        # Check if we've found enough companies already
        unique_companies = get_unique_companies(all_customers)
        if len(unique_companies) >= max_results:
            logger.info(f"Found {len(unique_companies)} unique companies from main page, which meets our target of {max_results}. Stopping early.")
            metrics['early_exit'] = True
            metrics['current_page'] = domain  # Add the current page to metrics
            metrics['status'] = 'complete'
            
            # Final callback before returning
            if status_callback:
                status_callback(metrics.copy())
                
            return format_results(unique_companies, vendor_name, metrics, max_results)
        
        # Keep track of how many unique companies we have as we go
        unique_count = len(unique_companies)
        logger.info(f"Found {unique_count}/{max_results} unique companies so far, continuing search...")
        
        # Update status to analyzing customer pages
        metrics['status'] = 'analyzing_customer_pages'
        metrics['current_customer_page_index'] = 0
        metrics['total_customer_pages'] = len(customer_page_links)
        if status_callback:
            status_callback(metrics.copy())
        
        # Analyze each customer page with Grok
        for index, page_url in enumerate(customer_page_links):
            try:
                # Update current page index and URL
                metrics['current_customer_page_index'] = index + 1
                metrics['current_page'] = page_url
                if status_callback:
                    status_callback(metrics.copy())
                
                logger.info(f"Fetching customer page: {page_url}")
                page_response = requests.get(page_url, timeout=15)
                
                if page_response.status_code != 200:
                    logger.warning(f"Failed to access customer page {page_url}, status code: {page_response.status_code}")
                    continue
                    
                metrics['pages_checked'] += 1
                page_text = extract_text_from_html(page_response.text)
                
                # Extract companies using Grok
                logger.info(f"Analyzing customer page content with Grok: {page_url}")
                metrics['status'] = 'analyzing_page_content'
                if status_callback:
                    status_callback(metrics.copy())
                    
                page_customers = extract_companies_with_grok(page_text, page_url, vendor_name)
                metrics['grok_api_calls'] += 1
                
                all_customers.extend(page_customers)
                metrics['companies_found'] += len(page_customers)
                
                logger.info(f"Found {len(page_customers)} companies from page {page_url}")
                
                # Check if we've found enough unique companies
                unique_companies = get_unique_companies(all_customers)
                unique_count = len(unique_companies)
                logger.info(f"Now have {unique_count}/{max_results} unique companies")
                
                # Update status with processing results
                metrics['status'] = 'processing_results'
                metrics['unique_companies_count'] = unique_count
                if status_callback:
                    status_callback(metrics.copy())
                
                if unique_count >= max_results:
                    logger.info(f"Reached target of {max_results} unique companies. Stopping search early.")
                    metrics['early_exit'] = True
                    metrics['current_page'] = page_url  # Add the current page to metrics
                    metrics['status'] = 'complete'
                    
                    # Final callback before returning
                    if status_callback:
                        status_callback(metrics.copy())
                        
                    return format_results(unique_companies, vendor_name, metrics, max_results)
                
            except Exception as e:
                logger.error(f"Error processing customer page {page_url}: {str(e)}")
                metrics['status'] = 'error_processing_page'
                metrics['last_error'] = str(e)
                if status_callback:
                    status_callback(metrics.copy())
                continue
        
        # Process results for normal termination - no more pages to process
        metrics['current_page'] = "Done - All pages processed"
        metrics['status'] = 'complete'
        
        # Final callback before returning
        if status_callback:
            status_callback(metrics.copy())
            
        return format_results(get_unique_companies(all_customers), vendor_name, metrics, max_results)
        
    except Exception as e:
        logger.exception(f"Error in enhanced vendor search for {vendor_name}: {str(e)}")
        
        # Log failure metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'error'
        metrics['error_type'] = type(e).__name__
        metrics['error_message'] = str(e)
        log_data_metrics(logger, "enhanced_vendor_search", metrics)
        
        # Final error callback
        if status_callback:
            status_callback(metrics.copy())
            
        return []