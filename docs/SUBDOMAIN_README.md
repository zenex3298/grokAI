# Okta Customer Subdomain Scraper

This document outlines the implementation plan for a feature to retrieve URLs from Okta customer subdomains following the pattern `https://www.okta.com/customers/SUBDOMAIN`.

## Architecture Overview

The feature will be implemented as a new scraper module that integrates with the existing application structure:

- **New Module**: `src/scrapers/okta_customer_pages.py`
- **Integration Point**: Worker process in `worker.py`
- **Data Flow**: Scraper → Data Processing → Results API

## Implementation Plan

### 1. Core Functionality

The scraper will:
- Generate potential Okta customer subdomain URLs
- Validate each subdomain for existence and relevance
- Extract company information from valid pages
- Format and return the results in a consistent structure

### 2. Technical Implementation

```python
import requests
from bs4 import BeautifulSoup
import time
import re
from urllib.parse import urljoin
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.utils.logger import get_logger, LogComponent, set_context, log_data_metrics, log_function_call

# Get a logger for this component
logger = get_logger(LogComponent.SCRAPER)

@log_function_call
def scrape_okta_customer_pages(vendor_name, max_results=20, status_callback=None):
    """
    Scrape Okta customer pages with the pattern https://www.okta.com/customers/SUBDOMAIN
    
    Args:
        vendor_name: Name of the vendor (for consistency with other scrapers)
        max_results: Maximum number of results to return
        status_callback: Optional callback function to report progress
        
    Returns:
        List of dictionaries containing customer data
    """
    # Set context for logging
    set_context(vendor_name=vendor_name, operation="okta_customer_pages")
    
    # Initialize metrics
    metrics = {
        'start_time': time.time(),
        'pages_checked': 0,
        'valid_pages': 0,
        'companies_found': 0,
        'status': 'started'
    }
    
    # Report initial progress
    if status_callback:
        status_callback(metrics.copy())
    
    try:
        # Define base URL
        base_url = "https://www.okta.com/customers/"
        
        # Get potential subdomains
        potential_subdomains = []
        
        # Method 1: Crawl the main customers page
        customers_url = "https://www.okta.com/customers/"
        try:
            response = requests.get(customers_url, timeout=30)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Find all links to customer pages
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    if '/customers/' in href and href != '/customers/':
                        # Extract the subdomain part
                        subdomain = href.split('/customers/')[-1].split('/')[0]
                        if subdomain:
                            potential_subdomains.append(subdomain)
        except Exception as e:
            logger.error(f"Error crawling main customers page: {str(e)}")
        
        # Method 2: Use predefined list of common company names
        common_companies = [
            "adobe", "expedia", "splunk", "box", "netflix",
            "cisco", "fedex", "jetblue", "western-union", "mgm-resorts",
            # Add more potential companies here
        ]
        potential_subdomains.extend(common_companies)
        
        # Remove duplicates
        potential_subdomains = list(set(potential_subdomains))
        
        # Report progress on subdomain discovery
        metrics['potential_subdomains'] = len(potential_subdomains)
        metrics['status'] = 'subdomains_discovered'
        if status_callback:
            status_callback(metrics.copy())
        
        # Process each potential subdomain
        results = []
        for subdomain in potential_subdomains:
            # Update metrics
            metrics['pages_checked'] += 1
            
            # Create the full URL
            url = base_url + subdomain
            
            try:
                # Try to access the page
                response = requests.get(url, timeout=30)
                
                # Check if the page exists
                if response.status_code == 200:
                    # Parse the HTML
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # Extract the company name (could be in different places)
                    company_name = ""
                    title_tag = soup.find('title')
                    if title_tag:
                        # Extract from title
                        title_text = title_tag.text
                        # Various patterns for extraction from title
                        if "|" in title_text:
                            company_name = title_text.split("|")[0].strip()
                        elif "-" in title_text:
                            company_name = title_text.split("-")[0].strip()
                        else:
                            company_name = title_text.strip()
                    
                    # If no name found, use the subdomain
                    if not company_name:
                        company_name = subdomain.replace("-", " ").title()
                    
                    # Create result object
                    result = {
                        'name': company_name,
                        'url': url,
                        'source': 'Okta Customer Page'
                    }
                    
                    # Add to results
                    results.append(result)
                    
                    # Update metrics
                    metrics['valid_pages'] += 1
                    metrics['companies_found'] += 1
                    
                    # Report progress
                    metrics['status'] = 'company_found'
                    metrics['current_company'] = company_name
                    if status_callback:
                        status_callback(metrics.copy())
                    
                    # Check if we've reached the maximum
                    if len(results) >= max_results:
                        logger.info(f"Reached maximum results ({max_results}), stopping search")
                        break
                
            except Exception as e:
                logger.error(f"Error processing subdomain {subdomain}: {str(e)}")
            
            # Periodic progress update
            if metrics['pages_checked'] % 5 == 0:
                metrics['status'] = 'processing'
                if status_callback:
                    status_callback(metrics.copy())
        
        # Final metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'completed'
        log_data_metrics(logger, "okta_customer_pages", metrics)
        
        # Final callback
        if status_callback:
            status_callback(metrics.copy())
        
        # Return the results
        return results
    
    except Exception as e:
        logger.exception(f"Error in Okta customer pages scraper: {str(e)}")
        
        # Log error metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'error'
        metrics['error'] = str(e)
        log_data_metrics(logger, "okta_customer_pages", metrics)
        
        # Error callback
        if status_callback:
            status_callback(metrics.copy())
        
        # Return empty results on error
        return []
```

## Heroku Compatibility Analysis

The application is currently deployed on Heroku, which introduces specific constraints that need to be addressed in the implementation.

### Heroku Architecture Support
1. **Dyno Structure**: The application already uses a web/worker dyno setup (as seen in Procfile), which is optimal for Heroku:
   - `web: python app.py` - Handles web requests
   - `worker: python worker.py` - Handles background processing

2. **Long-running Processes**: The worker.py is specifically designed for long-running tasks without timeouts, which addresses one of Heroku's main limitations (30-second request timeout on web dynos).

### Potential Heroku Limitations

1. **Memory Constraints**:
   - Heroku Free and Hobby dynos have limited memory (512MB-1GB)
   - The current implementation might use substantial memory when performing many parallel HTTP requests
   - Solution: Implement rate limiting and batch processing in the scraper

2. **Request Concurrency**:
   - Large-scale subdomain scanning could create hundreds of concurrent HTTP requests
   - Solution: Limit concurrent requests using ThreadPoolExecutor with reasonable max_workers

3. **Connection Limits**:
   - Heroku has limits on concurrent connections
   - Solution: Use connection pooling and rate limiting

4. **Ephemeral Filesystem**:
   - Heroku's filesystem is ephemeral, but this isn't an issue as the application doesn't rely on persistent file storage
   - Results are stored in memory and returned through the API

5. **Sleeping Dynos**:
   - On free tier, dynos sleep after 30 minutes of inactivity
   - Solution: Use a paid dyno or implement a ping service to keep the application active

### Required Modifications for Heroku

1. **Rate Limiting**:
   ```python
   # Add rate limiting to prevent too many requests
   with ThreadPoolExecutor(max_workers=5) as executor:  # Reduce from 10 to 5
       # Add time.sleep between requests
       time.sleep(1)  # Add delay between requests
   ```

2. **Memory Optimization**:
   ```python
   # Process in smaller batches to reduce memory usage
   batch_size = 20  # Process 20 subdomains at a time
   for i in range(0, len(potential_subdomains), batch_size):
       batch = potential_subdomains[i:i+batch_size]
       # Process batch...
   ```

3. **Timeouts and Error Handling**:
   ```python
   # Reduce timeout duration
   response = requests.get(url, timeout=5)  # Reduce from 30 to 5 seconds
   
   # Add more robust error handling
   except requests.exceptions.Timeout:
       logger.warning(f"Request timed out for {subdomain}")
       return {"url": url, "is_valid": False, "reason": "Request timed out"}
   ```

4. **Redis Integration**:
   The app already has Redis in requirements.txt, which is perfect for Heroku. We should leverage Redis for:
   - Storing job results (instead of in-memory dictionary)
   - Managing job queue (instead of Python's queue)
   - Caching previously checked subdomains

   ```python
   # Use Redis for result storage
   import redis
   r = redis.from_url(os.environ.get("REDIS_URL"))
   r.set(f"job:{job_id}:results", json.dumps(formatted_results))
   ```

## Final Heroku Implementation Recommendations

1. **Yes, the implementation would work on Heroku** with some optimizations.

2. **Recommended Dyno Configuration**:
   - 1 web dyno (Standard-1X or better)
   - 1-2 worker dynos (Standard-1X or better)
   - Redis add-on (at least Hobby Dev plan)

3. **Key Optimizations**:
   - Stagger requests with deliberate delays between batches
   - Limit concurrent connections to 5-10 maximum
   - Implement aggressive timeouts (5 seconds max)
   - Store all job data in Redis instead of in-memory
   - Implement checkpoint/resume functionality for resilience
   - Add automatic retry with exponential backoff

4. **Code Example for Heroku-Optimized Subdomain Checking**:

```python
def check_okta_subdomains_heroku_optimized(subdomains, job_id):
    """Heroku-optimized version of subdomain checking."""
    results = []
    
    # Process in smaller batches
    batch_size = 10
    for i in range(0, len(subdomains), batch_size):
        batch = subdomains[i:i+batch_size]
        
        # Process batch with limited concurrency
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(check_okta_subdomain, subdomain): subdomain for subdomain in batch}
            
            for future in as_completed(futures):
                subdomain = futures[future]
                try:
                    result = future.result()
                    if result and result.get('is_valid'):
                        # Store to Redis instead of in-memory
                        r.lpush(f"job:{job_id}:valid_subdomains", json.dumps(result))
                        
                        # Also keep in local results for this batch
                        results.append(result)
                except Exception as e:
                    logger.error(f"Error checking subdomain {subdomain}: {str(e)}")
        
        # Add delay between batches to avoid overwhelming Heroku
        time.sleep(2)
    
    return results
```

## Integration Steps

1. Create the new file `src/scrapers/okta_customer_pages.py`
2. Add the import to `worker.py`
3. Add a callback handler and function call in the worker process
4. Update the results processing logic to include Okta customer data in the combined results

## Testing Plan

1. Test with a small set of known Okta customer subdomains
2. Monitor memory usage and execution time on development environment
3. Perform load testing with different batch sizes and concurrency settings
4. Verify results are correctly integrated with the existing data sources

## Edge Cases and Considerations

1. **Rate Limiting**: Implement rate limiting to avoid being blocked by Okta
2. **Non-existent Pages**: Handle 404 responses for non-existent subdomains
3. **Redirects**: Handle URL redirects properly
4. **Execution Time**: Limit crawling depth to manage execution time
5. **Browser Detection**: Some sites may block automated requests