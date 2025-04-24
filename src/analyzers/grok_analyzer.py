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

def analyze_with_grok(data, vendor_name, progress_callback=None, max_results=20):
    """
    Analyze collected data using Grok AI.
    
    Args:
        data: List of data items to analyze
        vendor_name: Name of the vendor
        progress_callback: Optional callback function to report progress
                          Callback signature: func(stage, partial_results=None, message=None)
        max_results: Maximum number of results to return (default: 20)
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
        
        # Limit formatted data size if too large, but allow more data than before
        max_chars = 10000  # Increased from 7000 to 10000
        if len(formatted_data) > max_chars:
            logger.warning(f"Data too large ({len(formatted_data)} chars), truncating to {max_chars} chars")
            formatted_data = formatted_data[:max_chars] + "..."
            
        # Prepare enhanced prompt for Grok with improved filtering
        prompt = f"""
        Analyze this customer data for {vendor_name}:

        {formatted_data}

        TASK: Thoroughly analyze this data and identify ONLY legitimate company names that appear to be customers or clients of {vendor_name}.

        IMPORTANT: Take your time to analyze the entire content. You MUST spend at least 45-60 seconds analyzing the data.
        
        CRITICAL FILTERING INSTRUCTIONS:
        - DO NOT include navigation menu items, category names, or UI elements
        - DO NOT include generic headings like "Trusted by" or "Our Customers"
        - DO NOT include slogans, marketing copy, or promotional text
        - DO NOT include general phrases that aren't company names
        - DO NOT include descriptive sections like "Government and Public Sector"
        - A real company name typically includes terms like Inc, LLC, Ltd, GmbH, or has a distinctive brand name
        - Focus on names that have actual evidence of being customers in the text
        
        Look for indicators that suggest these companies are customers, such as:
        - Company names mentioned in testimonial contexts
        - Companies described as "using" or "choosing" {vendor_name}
        - Companies listed as case studies or success stories
        - Any company presented as a customer reference with clear evidence

        Please respond with each customer on a new line, following this format:
        Company Name

        Only include companies that you believe are actual customers with at least 80% confidence.
        Do not include {vendor_name} itself or generic terms.
        
        You MUST take at least 45-60 seconds to thoroughly process this content before responding.
        Provide a thorough analysis as your response is critical for business intelligence.
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
                {'role': 'system', 'content': 'You are a helpful assistant that identifies unique customer names from provided data.'},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 2000,  # Increased max tokens for longer responses
            'temperature': 0,  # Lower temperature for more deterministic responses
            'timeout': 50      # Add explicit timeout parameter for the model
        }
        
        # Add retry logic - try up to 3 times with increasing timeouts
        max_retries = 3
        initial_timeout = 40  # Increased: Start with 40 seconds timeout
        
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
                    return process_data_without_grok(data, vendor_name, progress_callback, max_results)
                    
                # Wait before retrying
                time.sleep(2)  # Add a small delay between retries
                
            except requests.exceptions.Timeout:
                logger.warning(f"X.AI API request timed out after {current_timeout} seconds on attempt {retry+1}")
                
                if retry == max_retries - 1:
                    # This was our last attempt
                    logger.error(f"All {max_retries} API attempts timed out")
                    logger.info("Falling back to processing without Grok due to timeout")
                    return process_data_without_grok(data, vendor_name, progress_callback, max_results)
                    
                # Wait before retrying
                time.sleep(2)  # Add a small delay between retries
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error with X.AI API on attempt {retry+1}: {str(e)}")
                logger.info("Falling back to processing without Grok due to request error")
                return process_data_without_grok(data, vendor_name, progress_callback, max_results)
        
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
            return process_data_without_grok(data, vendor_name, progress_callback, max_results)
        
        # Process X.AI's response
        grok_response = response.json()
        generated_text = grok_response.get('choices', [{}])[0].get('message', {}).get('content', '')
        logger.info(f"Received valid response from X.AI API: {len(generated_text)} characters")
        
        # Update progress for final processing
        if progress_callback:
            progress_callback('FINALIZING', partial_results, 'Finalizing results from API response')
            
        # Parse the generated text into structured data with result limit
        logger.info(f"Limiting results to maximum of {max_results}")
        results = parse_grok_response(generated_text, vendor_name, max_results)
        
        # Log number of results
        logger.info(f"Returning {len(results)} results out of potentially more")
        
        # Final progress update with complete results
        if progress_callback:
            progress_callback('COMPLETE', results, f'Analysis complete! (Limited to {max_results} results)')
            
        return results
    
    except Exception as e:
        logger.error(f"Error analyzing with X.AI/Grok: {str(e)}")
        logger.info("Falling back to processing without Grok due to error")
        if progress_callback:
            progress_callback('ERROR', partial_results, f'Error: {str(e)}')
        return process_data_without_grok(data, vendor_name, progress_callback, max_results)

def parse_grok_response(text, vendor_name, max_results=5):
    """Parse Grok's response text into structured format.
    
    Args:
        text: The text response from Grok
        vendor_name: The name of the vendor
        max_results: Maximum number of results to return (default: 20)
    """
    all_results = []
    
    # First try to parse as JSON
    try:
        # Try to extract just the JSON part if there's any surrounding text
        json_start = text.find('[')
        json_end = text.rfind(']') + 1
        
        if json_start >= 0 and json_end > json_start:
            json_str = text[json_start:json_end]
            companies_data = json.loads(json_str)
            
            # Process JSON format
            for company in companies_data:
                if isinstance(company, dict) and 'company_name' in company:
                    name = company['company_name']
                    confidence = company.get('confidence', 0.7)  # Default confidence
                    
                    if confidence >= 0.6:  # Only include companies with sufficient confidence
                        all_results.append({
                            'competitor': vendor_name,
                            'customer_name': name,
                            'customer_url': f"{name.lower().replace(' ', '')}.com",
                            'confidence': confidence,
                            'reason': company.get('reason', 'Extracted by Grok')
                        })
            
            # If we successfully parsed JSON, sort by confidence and return top results
            if all_results:
                # Sort by confidence (highest first)
                all_results = sorted(all_results, key=lambda x: x.get('confidence', 0), reverse=True)
                # Limit to max_results
                return all_results[:max_results]
    except:
        # If JSON parsing fails, fall back to line-by-line parsing
        logger.info("JSON parsing failed, falling back to line-by-line parsing")
        pass
    
    # If we get here, try the old line-by-line parsing method
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
            
            # Stop if we've reached the maximum number of results
            if len(results) >= max_results:
                logger.info(f"Reached maximum of {max_results} results, truncating")
                break
    
    return results

def process_data_without_grok(data, vendor_name, progress_callback=None, max_results=20):
    """Process data without using Grok AI.
    
    Args:
        data: List of data items to analyze
        vendor_name: Name of the vendor
        progress_callback: Optional callback function to report progress
        max_results: Maximum number of results to return (default: 20)
    """
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
    
    # Limit results
    if len(results) > max_results:
        logger.info(f"Limiting non-Grok results from {len(results)} to {max_results}")
        results = results[:max_results]
    
    # Final progress update if callback provided
    if progress_callback:
        progress_callback('COMPLETE', results, f'Analysis complete! (Limited to {max_results} results)')
        
    return results

def cleanup_url(url):
    """Clean and validate URL."""
    # If URL is empty or None, return None
    if not url:
        return None
        
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
    
    # Validate URL has proper domain structure
    if len(url) < 4 or '.' not in url:
        return None
    
    return url
