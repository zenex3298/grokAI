import os
import json
import logging
import requests
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

def analyze_with_grok(data, vendor_name):
    """Analyze collected data using Grok AI."""
    try:
        # Get Grok API key from environment
        api_key = os.environ.get('GROK_API_KEY')
        
        if not api_key:
            logger.error("GROK_API_KEY not found in environment variables")
            return process_data_without_grok(data, vendor_name)
        
        # Format data for Grok API
        formatted_data = json.dumps(data, indent=2)
        
        # Prepare prompt for Grok
        prompt = f"""
        Here's a collection of data about customers of {vendor_name}:

        {formatted_data}

        Please analyze this data and identify unique customers. For each customer, extract their name and website URL if available.
        If the URL is not available, use your knowledge to provide the most likely official website domain.
        Format your response as a clean list of uniquely identified customers without duplicates.
        For each entry include: Customer Name, Website URL
        """
        
        # Call Grok API
        # Note: This is a placeholder. Actual implementation will depend on Grok's API specifications
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'prompt': prompt,
            'max_tokens': 1000
        }
        
        response = requests.post(
            'https://api.grok.ai/v1/completions',  # Placeholder URL
            headers=headers,
            json=payload
        )
        
        if response.status_code != 200:
            logger.error(f"Grok API error: {response.status_code}")
            return process_data_without_grok(data, vendor_name)
        
        # Process Grok's response
        grok_response = response.json()
        generated_text = grok_response.get('choices', [{}])[0].get('text', '')
        
        # Parse the generated text into structured data
        return parse_grok_response(generated_text, vendor_name)
    
    except Exception as e:
        logger.error(f"Error analyzing with Grok: {str(e)}")
        return process_data_without_grok(data, vendor_name)

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

def process_data_without_grok(data, vendor_name):
    """Process data without using Grok AI."""
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
