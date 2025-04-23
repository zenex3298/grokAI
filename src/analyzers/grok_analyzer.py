import os
import json
import requests
import time
import copy
from urllib.parse import urlparse
from datetime import datetime

from src.utils.logger import get_logger, LogComponent, set_context, log_data_metrics, log_function_call

# Get a logger specifically for the analyzer component
logger = get_logger(LogComponent.GROK)

def analyze_with_grok(data, vendor_name, progress_callback=None):
    """
    Analyze collected data using Grok AI.
    
    Args:
        data: List of data items to analyze
        vendor_name: Name of the vendor
        progress_callback: Optional callback function to report progress
                          Callback signature: func(stage, partial_results=None, message=None)
    """
    try:
        # Report initial progress
        if progress_callback:
            progress_callback('PREPARING', message='Preparing data for analysis')
            
        # Get Grok API key from environment
        api_key = os.environ.get('GROK_API_KEY')
        
        if not api_key:
            logger.error("GROK_API_KEY not found in environment variables")
            return process_data_without_grok(data, vendor_name, progress_callback)
        
        # Format data for Grok API
        # Format regular data for Grok API, but limit the size
        simplified_data = []
        
        # Initial basic processing to generate partial results
        partial_results = []
        
        for i, item in enumerate(data):
            # Create simplified version with just essential fields
            simple_item = {
                "name": item.get("name", ""),
                "url": item.get("url", ""),
                "source": item.get("source", "")
            }
            simplified_data.append(simple_item)
            
            # Every 10 items, update progress
            if progress_callback and i > 0 and i % 10 == 0:
                progress_percent = min(50, int((i / len(data)) * 50))  # Map to 0-50% range for data preparation
                progress_callback(progress_percent, partial_results, f'Preparing data: {i}/{len(data)} items')
            
            # Add to partial results (with basic processing)
            name = item.get("name", "").strip()
            if name and name.lower() != vendor_name.lower():
                url = cleanup_url(item.get("url", "") or f"{name.lower().replace(' ', '')}.com")
                
                # Simple deduplication by name
                if not any(r['customer_name'].lower() == name.lower() for r in partial_results):
                    partial_results.append({
                        'competitor': vendor_name,
                        'customer_name': name,
                        'customer_url': url
                    })
        
        # Report partial results 
        if progress_callback:
            progress_callback(50, partial_results, 'Basic analysis complete, proceeding with AI analysis')
            
        formatted_data = json.dumps(simplified_data, indent=0)  # Reduce indentation
        
        # Limit formatted data size if too large
        if len(formatted_data) > 7000:
            logger.warning(f"Data too large ({len(formatted_data)} chars), truncating to 7000 chars")
            formatted_data = formatted_data[:7000] + "..."
            
        # Prepare prompt for Grok (shortened)
        prompt = f"""
        Analyze this customer data for {vendor_name}:

        {formatted_data}

        Extract customer names and website URLs. Format each entry as: Customer Name, Website URL
        """
        
        # Call X.AI API with proper authentication (since our key is X.AI format)
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'VendorCustomerIntelligenceTool/1.0',  # Proper user agent
            'X-Request-ID': f'{vendor_name}-{int(time.time())}'  # For tracking requests
        }
        
        # Log API request details
        logger.info(f"Sending request to X.AI API with payload size: {len(json.dumps(prompt))} characters")
        
        # Create payload directly in the request
        logger.info("Calling X.AI API for customer identification")
        
        # Update progress to API call stage
        if progress_callback:
            progress_callback('API_CALL', partial_results, 'Sending request to X.AI API for analysis')
        
        # Define API payload
        api_payload = {
            'model': 'grok-3-latest',  # Using Grok model that works in curl
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant that identifies unique customer names and their website URLs from provided data.'},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 1000,
            'temperature': 0  # Lower temperature for more deterministic responses
        }
        
        # Add retry logic - try up to 3 times with increasing timeouts
        max_retries = 3
        initial_timeout = 20  # Start with 20 seconds
        
        for retry in range(max_retries):
            current_timeout = initial_timeout * (retry + 1)  # Increase timeout with each retry
            logger.info(f"API call attempt {retry+1}/{max_retries} with {current_timeout}s timeout")
            
            try:
                # Update progress for retry attempt
                if progress_callback:
                    progress_callback(60 + retry * 10, partial_results, f'API call attempt {retry+1}/{max_retries}')
                    
                response = requests.post(
                    'https://api.x.ai/v1/chat/completions',  # X.AI API endpoint
                    headers=headers,
                    timeout=current_timeout,
                    json=api_payload
                )
                logger.info(f"X.AI API request sent, status code: {response.status_code}")
                
                # If we got a response, break out of the retry loop
                if response.status_code == 200:
                    logger.info("Successful API response received")
                    if progress_callback:
                        progress_callback(85, partial_results, 'API call successful, processing response')
                    break
                    
                # If we got an error but not a timeout, log it and continue retrying
                logger.warning(f"API error on attempt {retry+1}: status={response.status_code}")
                
                if retry == max_retries - 1:
                    # This was our last attempt
                    logger.error(f"All {max_retries} API attempts failed, last status: {response.status_code}")
                    return process_data_without_grok(data, vendor_name)
                    
                # Wait before retrying
                time.sleep(2)  # Add a small delay between retries
                
            except requests.exceptions.Timeout:
                logger.warning(f"X.AI API request timed out after {current_timeout} seconds on attempt {retry+1}")
                
                if retry == max_retries - 1:
                    # This was our last attempt
                    logger.error(f"All {max_retries} API attempts timed out")
                    logger.info("Falling back to processing without Grok due to timeout")
                    return process_data_without_grok(data, vendor_name)
                    
                # Wait before retrying
                time.sleep(2)  # Add a small delay between retries
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error with X.AI API on attempt {retry+1}: {str(e)}")
                logger.info("Falling back to processing without Grok due to request error")
                return process_data_without_grok(data, vendor_name)
        
        if response.status_code != 200:
            error_response = None
            try:
                error_response = response.json()
            except:
                error_response = response.text

            logger.error(f"X.AI API error: {response.status_code} - {error_response}")
            logger.info("Falling back to processing without Grok")
            if progress_callback:
                progress_callback('ERROR', partial_results, f'API error: {response.status_code}')
            return process_data_without_grok(data, vendor_name, progress_callback)
        
        # Process X.AI's response
        grok_response = response.json()
        generated_text = grok_response.get('choices', [{}])[0].get('message', {}).get('content', '')
        logger.info(f"Received valid response from X.AI API: {len(generated_text)} characters")
        
        # Update progress for final processing
        if progress_callback:
            progress_callback('FINALIZING', partial_results, 'Finalizing results from API response')
            
        # Parse the generated text into structured data
        results = parse_grok_response(generated_text, vendor_name)
        
        # Final progress update with complete results
        if progress_callback:
            progress_callback('COMPLETE', results, 'Analysis complete!')
            
        return results
    
    except Exception as e:
        logger.error(f"Error analyzing with X.AI/Grok: {str(e)}")
        logger.info("Falling back to processing without Grok due to error")
        if progress_callback:
            progress_callback('ERROR', partial_results, f'Error: {str(e)}')
        return process_data_without_grok(data, vendor_name, progress_callback)

def parse_grok_response(text, vendor_name):
    """Parse Grok's response text into structured format."""
    results = []
    
    # Split by new lines and process each line
    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        # Try to extract customer name and URL
        parts = line.split(',', 1)
        if len(parts) >= 1:
            customer_name = parts[0].strip()
            if len(parts) > 1:
                url = parts[1].strip()
            else:
                url = f"{customer_name.lower().replace(' ', '')}.com"
            
            # Validate and cleanup URL
            url = cleanup_url(url)
            
            results.append({
                'competitor': vendor_name,
                'customer_name': customer_name,
                'customer_url': url
            })
    
    return results

def process_data_without_grok(data, vendor_name, progress_callback=None):
    """Process data without using Grok AI."""
    # Update progress if callback provided
    if progress_callback:
        progress_callback('FINALIZING', None, 'Processing data without AI')
        
    # Basic de-duplication by customer name
    unique_customers = {}
    
    for item in data:
        name = item.get('name')
        if not name:
            continue
            
        # Skip entries that match the vendor name
        if name.lower() == vendor_name.lower():
            continue
            
        # Use existing URL or generate one
        url = item.get('url')
        if not url:
            url = f"{name.lower().replace(' ', '')}.com"
        
        # Clean and validate URL
        url = cleanup_url(url)
        
        # Add to unique customers (overwriting any previous entry with same name)
        unique_customers[name] = url
    
    # Format results
    results = []
    for name, url in unique_customers.items():
        results.append({
            'competitor': vendor_name,
            'customer_name': name,
            'customer_url': url
        })
    
    # Final progress update if callback provided
    if progress_callback:
        progress_callback('COMPLETE', results, 'Analysis complete!')
        
    return results

def cleanup_url(url):
    """Clean and validate URL."""
    # Remove common prefixes if present
    url = url.strip()
    for prefix in ['http://', 'https://', 'www.']:
        if url.startswith(prefix):
            url = url[len(prefix):]
    
    # Remove path components and parameters
    parsed = urlparse(f"https://{url}")
    url = parsed.netloc
    
    # Ensure URL doesn't contain spaces or special characters
    url = url.lower().replace(' ', '')
    
    return url
