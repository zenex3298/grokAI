import os
import json
import requests
import time
import copy
from urllib.parse import urlparse
from datetime import datetime

from src.utils.logger import get_logger, LogComponent, set_context, log_data_metrics, log_function_call
from src.utils.url_validator import validate_url, log_validation_stats

# Get a logger specifically for the analyzer component
logger = get_logger(LogComponent.GROK)

def analyze_with_grok(data, vendor_name, progress_callback=None, max_results=20, custom_prompt=None):
    """
    Analyze collected data using Grok AI.
    
    Args:
        data: List of data items to analyze
        vendor_name: Name of the vendor
        progress_callback: Optional callback function to report progress
                          Callback signature: func(stage, partial_results=None, message=None)
        max_results: Maximum number of results to return (default: 20)
        custom_prompt: Optional custom prompt to override the default prompt
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
        
        # Track invalid URLs for logging
        invalid_urls_count = 0
        
        # Collect and validate all URLs in one pass
        original_urls = []
        validation_results = []
        
        for i, item in enumerate(data):
            # Get item URL or generate one from name
            name = item.get("name", "").strip()
            url = item.get("url", "")
            
            if not url and name and name.lower() != vendor_name.lower():
                # Generate URL from name if none exists
                url = f"{name.lower().replace(' ', '')}.com"
            
            if url:
                original_urls.append(url)
                # Validate URL structure only in first pass - much faster
                result = validate_url(url, validate_dns=False, validate_http=False)
                validation_results.append(result)
                
                # Only include items with valid URL structure 
                if result.structure_valid:
                    # Create simplified version with just essential fields
                    simple_item = {
                        "name": item.get("name", ""),
                        "url": result.cleaned_url,
                        "source": item.get("source", "")
                    }
                    simplified_data.append(simple_item)
                    
                    # Add to partial results with deduplication
                    if name and name.lower() != vendor_name.lower():
                        if not any(r['customer_name'].lower() == name.lower() for r in partial_results):
                            partial_results.append({
                                'competitor': vendor_name,
                                'customer_name': name,
                                'customer_url': result.cleaned_url,
                                'validation': {
                                    'structure_valid': result.structure_valid,
                                    'dns_valid': result.dns_valid,
                                    'http_valid': result.http_valid
                                }
                            })
            
            # Update progress periodically
            if progress_callback and i > 0 and i % 10 == 0:
                progress_percent = min(30, int((i / len(data)) * 30))  # Map to 0-30% range for basic validation
                progress_callback(progress_percent, partial_results, f'Validating data: {i}/{len(data)} items')
        
        # Log validation statistics for structure validation
        log_validation_stats(
            original_urls, 
            validation_results, 
            context={'stage': 'structure_validation', 'vendor': vendor_name}
        )
        
        # Structure validation results
        invalid_structure_count = sum(1 for r in validation_results if not r.structure_valid)
        if invalid_structure_count > 0:
            logger.info(f"Removed {invalid_structure_count} URLs with invalid structure")
        
        # Perform DNS validation on URLs that passed structure validation
        if simplified_data:
            # Update progress for DNS validation stage
            if progress_callback:
                progress_callback(30, partial_results, 'Validating URLs via DNS lookups')
            
            # Track validation results
            dns_validation_results = []
            dns_validated_data = []
            dns_original_urls = []
            
            # Validate batches of URLs to avoid overwhelming DNS
            batch_size = 10
            for i in range(0, len(simplified_data), batch_size):
                batch = simplified_data[i:i+batch_size]
                
                # Update progress for each batch
                if progress_callback:
                    progress_percent = 30 + min(10, int((i / len(simplified_data)) * 10))  # Map to 30-40% range
                    progress_callback(progress_percent, partial_results, f'DNS validating: {i}/{len(simplified_data)}')
                
                # Validate each URL in the batch
                for item in batch:
                    url = item["url"]
                    dns_original_urls.append(url)
                    
                    # DNS validation
                    result = validate_url(url, validate_dns=True, validate_http=False)
                    dns_validation_results.append(result)
                    
                    if result.dns_valid:
                        dns_validated_data.append(item)
            
            # Log DNS validation statistics
            log_validation_stats(
                dns_original_urls, 
                dns_validation_results, 
                context={'stage': 'dns_validation', 'vendor': vendor_name}
            )
            
            # DNS validation results  
            dns_invalid_count = sum(1 for r in dns_validation_results if not r.dns_valid)
            if dns_invalid_count > 0:
                logger.info(f"DNS validation removed {dns_invalid_count} invalid URLs")
            
            # HTTP validation (optional, limited subset)
            # This is most expensive, so only do it on a subset that passed DNS validation
            if dns_validated_data and len(dns_validated_data) > 5:
                # Update progress for HTTP validation stage
                if progress_callback:
                    progress_callback(40, partial_results, 'Validating URLs via HTTP requests')
                
                # Limit HTTP validation to reduce load
                http_validation_limit = min(50, len(dns_validated_data))
                http_validated_data = []
                http_validation_results = []
                http_original_urls = []
                
                # Process HTTP validation in small batches 
                batch_size = 5
                for i in range(0, http_validation_limit, batch_size):
                    batch = dns_validated_data[i:i+batch_size]
                    
                    # Update progress for each batch
                    if progress_callback:
                        progress_percent = 40 + min(10, int((i / http_validation_limit) * 10))  # Map to 40-50% range
                        progress_callback(progress_percent, partial_results, f'HTTP validating: {i}/{http_validation_limit}')
                    
                    # Validate each URL in the batch
                    for item in batch:
                        url = item["url"]
                        http_original_urls.append(url)
                        
                        # HTTP validation
                        result = validate_url(url, validate_dns=False, validate_http=True)
                        http_validation_results.append(result)
                        
                        if result.http_valid:
                            http_validated_data.append(item)
                
                # Log HTTP validation statistics
                log_validation_stats(
                    http_original_urls, 
                    http_validation_results, 
                    context={'stage': 'http_validation', 'vendor': vendor_name}
                )
                
                # HTTP validation results
                http_invalid_count = sum(1 for r in http_validation_results if not r.http_valid)
                if http_invalid_count > 0:
                    logger.info(f"HTTP validation removed {http_invalid_count} invalid URLs")
                
                # Use HTTP validated data if we have enough
                if len(http_validated_data) >= 5:  
                    logger.info(f"Using {len(http_validated_data)} HTTP-validated URLs for analysis")
                    simplified_data = http_validated_data
                else:
                    # If too few URLs pass HTTP validation, fall back to DNS validation
                    logger.warning(f"HTTP validation left only {len(http_validated_data)} valid URLs. Falling back to DNS validation.")
                    simplified_data = dns_validated_data
            else:
                # If DNS validation left too few results, use structure-validated data
                if len(dns_validated_data) < 5:
                    logger.warning(f"DNS validation left only {len(dns_validated_data)} valid URLs. Using structure-validated URLs.")
                else:
                    logger.info(f"Using {len(dns_validated_data)} DNS-validated URLs for analysis")
                    simplified_data = dns_validated_data
        
        # Log final validation status
        logger.info(f"Total URLs after validation: {len(simplified_data)}")
        if len(simplified_data) == 0:
            logger.warning("No valid URLs to send to Grok for analysis")
        
        # Report partial results 
        if progress_callback:
            progress_callback(50, partial_results, 'Basic analysis complete, proceeding with AI analysis')
            
        formatted_data = json.dumps(simplified_data, indent=0)  # Reduce indentation
        
        # Limit formatted data size if too large, but allow more data than before
        max_chars = 10000  # Increased from 7000 to 10000
        if len(formatted_data) > max_chars:
            logger.warning(f"Data too large ({len(formatted_data)} chars), truncating to {max_chars} chars")
            formatted_data = formatted_data[:max_chars] + "..."
            
        if custom_prompt:
            # Use the custom prompt if provided
            # Replace {search_data} with formatted_data in the custom prompt
            prompt = custom_prompt.replace("{search_data}", formatted_data)
            logger.info("Using custom prompt for Grok analysis")
        else:
            # Prepare default enhanced prompt for Grok with improved filtering
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
        
        # Log ALL URLs analyzed by Grok regardless of whether they passed validation
        validation_summary = {}
        if results:
            logger.info(f"Final list of {len(results)} validated URLs from Grok:")
            for i, result in enumerate(results):
                url = result.get('customer_url')
                name = result.get('customer_name', 'Unknown')
                validation_info = result.get('validation', {})
                structure_valid = validation_info.get('structure_valid', False)
                dns_valid = validation_info.get('dns_valid', False)
                http_valid = validation_info.get('http_valid', False)
                
                # Track validation counts
                validation_summary['total'] = validation_summary.get('total', 0) + 1
                if structure_valid:
                    validation_summary['structure_valid'] = validation_summary.get('structure_valid', 0) + 1
                if dns_valid:
                    validation_summary['dns_valid'] = validation_summary.get('dns_valid', 0) + 1
                if http_valid:
                    validation_summary['http_valid'] = validation_summary.get('http_valid', 0) + 1
                    
                logger.info(f"  {i+1}. {name}: {url} [structure:{structure_valid}, dns:{dns_valid}, http:{http_valid}]")
        
            # Log validation summary
            total = validation_summary.get('total', 0)
            structure_valid = validation_summary.get('structure_valid', 0)
            dns_valid = validation_summary.get('dns_valid', 0)
            http_valid = validation_summary.get('http_valid', 0)
            
            logger.info(f"Grok URL validation summary: {structure_valid}/{total} structure valid, "
                        f"{dns_valid}/{total} DNS valid, {http_valid}/{total} HTTP valid")
        else:
            logger.warning("No URLs from Grok analysis")
        
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
    
    # Keep track of validation for logging
    original_urls = []
    validation_results = []
    
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
                        # Generate URL from name or use provided URL
                        url = None
                        if 'url' in company and company['url']:
                            url = company['url']
                        else:
                            url = f"{name.lower().replace(' ', '')}.com"
                        
                        if url:
                            original_urls.append(url)
                            # Only validate structure - we'll validate DNS later if needed
                            validation_result = validate_url(url, validate_dns=False, validate_http=False)
                            validation_results.append(validation_result)
                            
                            # Only include if URL structure is valid
                            if validation_result.structure_valid:
                                all_results.append({
                                    'competitor': vendor_name,
                                    'customer_name': name,
                                    'customer_url': validation_result.cleaned_url,
                                    'confidence': confidence,
                                    'reason': company.get('reason', 'Extracted by Grok'),
                                    'validation': {
                                        'structure_valid': validation_result.structure_valid,
                                        'dns_valid': validation_result.dns_valid,
                                        'http_valid': validation_result.http_valid
                                    }
                                })
            
            # Log validation statistics
            log_validation_stats(
                original_urls, 
                validation_results, 
                context={'stage': 'grok_json_response', 'vendor': vendor_name}
            )
            
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
    
    # Reset validation tracking for line-by-line method
    original_urls = []
    validation_results = []
    
    # Split by new lines and process each line
    lines = text.strip().split('\n')
    
    # Check if the response indicates no companies were found
    if any(line.strip() == 'NO_COMPANIES_FOUND' for line in lines):
        logger.info("Grok response indicates no companies were found")
        return results
        
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or line.lower() == 'no_companies_found':
            continue
        
        # Try to extract customer name and URL
        parts = line.split(',', 1)
        if len(parts) >= 1:
            customer_name = parts[0].strip()
            if len(parts) > 1:
                url = parts[1].strip()
            else:
                url = f"{customer_name.lower().replace(' ', '')}.com"
            
            if url:
                original_urls.append(url)
                # Validate URL structure
                validation_result = validate_url(url, validate_dns=False, validate_http=False)
                validation_results.append(validation_result)
                
                # Only include if URL structure is valid
                if validation_result.structure_valid:
                    results.append({
                        'competitor': vendor_name,
                        'customer_name': customer_name,
                        'customer_url': validation_result.cleaned_url,
                        'validation': {
                            'structure_valid': validation_result.structure_valid,
                            'dns_valid': validation_result.dns_valid,
                            'http_valid': validation_result.http_valid
                        }
                    })
            
            # Stop if we've reached the maximum number of results
            if len(results) >= max_results:
                logger.info(f"Reached maximum of {max_results} results, truncating")
                break
    
    # Log validation statistics for line-by-line parsing
    log_validation_stats(
        original_urls, 
        validation_results, 
        context={'stage': 'grok_line_parsing', 'vendor': vendor_name}
    )
    
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
    
    # Track validation for logging
    original_urls = []
    validation_results = []
    
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
        
        if url:
            # Track for validation stats
            original_urls.append(url)
            
            # Validate URL with structure validation
            validation_result = validate_url(url, validate_dns=False, validate_http=False)
            validation_results.append(validation_result)
            
            # Only use if structure is valid
            if validation_result.structure_valid:
                # Add to unique customers (overwriting any previous entry with same name)
                unique_customers[name] = {
                    'url': validation_result.cleaned_url,
                    'validation': {
                        'structure_valid': validation_result.structure_valid,
                        'dns_valid': validation_result.dns_valid,
                        'http_valid': validation_result.http_valid
                    }
                }
    
    # Log validation statistics
    log_validation_stats(
        original_urls, 
        validation_results, 
        context={'stage': 'fallback_processing', 'vendor': vendor_name}
    )
    
    # Format results
    results = []
    for name, data in unique_customers.items():
        results.append({
            'competitor': vendor_name,
            'customer_name': name,
            'customer_url': data['url'],
            'validation': data['validation']
        })
    
    # Limit results
    if len(results) > max_results:
        logger.info(f"Limiting non-Grok results from {len(results)} to {max_results}")
        results = results[:max_results]
    
    # Log the final URLs that will be sent to the frontend
    if results:
        logger.info(f"Final list of {len(results)} validated URLs being sent to frontend (fallback mode):")
        for i, result in enumerate(results):
            url = result.get('customer_url')
            name = result.get('customer_name', 'Unknown')
            logger.info(f"  {i+1}. {name}: https://{url}")
    else:
        logger.warning("No valid URLs to send to frontend (fallback mode)")
    
    # Final progress update if callback provided
    if progress_callback:
        progress_callback('COMPLETE', results, f'Analysis complete! (Limited to {max_results} results)')
        
    return results

# These functions have been replaced by src.utils.url_validator
# They are kept as comments for reference in case needed

# def validate_url_http(url, timeout=2):
#     """Validate a URL by making a HEAD request to it."""
#     # Now using the central URL validator 
#     pass

# def cleanup_url(url, validate_http=False):
#     """Clean and validate URL."""
#     # Now using the central URL validator
#     pass
