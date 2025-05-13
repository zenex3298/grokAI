import os
import time
import json
import threading
import queue
from datetime import datetime

# Import required modules
from src.scrapers.vendor_site import scrape_vendor_site
from src.scrapers.enhanced_search import enhanced_vendor_search
from src.scrapers.featured_customers import scrape_featured_customers
from src.scrapers.search_engines import search_google
from src.scrapers.trust_radius import scrape_trust_radius
from src.scrapers.peerspot import scrape_peerspot
from src.scrapers.builtwith import scrape_builtwith
from src.scrapers.publicwww import scrape_publicwww
from src.utils.data_validator import validate_combined_data
from src.utils.logger import setup_logging, get_logger, LogComponent, set_context
from src.analyzers.grok_analyzer import cleanup_url
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logger = setup_logging()
worker_logger = get_logger(LogComponent.WORKER)
worker_logger.info("Worker process starting up")

# Initialize job tracking structures
job_results = {}
job_logs = {}
job_queue = queue.Queue()  # Queue for background processing

def process_vendor(job_id, vendor_name, max_results=20):
    """
    Process a vendor search job.
    
    This function handles the long-running vendor search process.
    It's designed to run in a worker dyno without timeout constraints.
    """
    worker_logger.info(f"Processing job {job_id} for vendor {vendor_name} with max_results: {max_results}")
    
    # Initialize job tracking
    job_results[job_id] = {
        'status': 'processing',
        'progress': {
            'step': 10,
            'message': f'Processing {vendor_name}...'
        },
        'metrics': {
            'pages_checked': 0,
            'customer_links_found': 0,
            'companies_found': 0,
            'unique_companies': 0,
            'target_count': max_results
        },
        'vendor_name': vendor_name,
        'max_results': max_results,
        'start_time': time.time()
    }
    
    # Initialize logs for this job
    job_logs[job_id] = []
    
    try:
        # Add initial log
        log_entry = {'type': 'info', 'message': f"Starting analysis for {vendor_name}...", 'timestamp': time.time()}
        job_logs[job_id].append(log_entry)
        
        # Update progress
        job_results[job_id]['progress'] = {
            'step': 20,
            'message': f'Searching vendor website for {vendor_name}...'
        }
        
        # Log entry for vendor site search
        log_entry = {'type': 'info', 'message': f"Searching vendor website for {vendor_name}...", 'timestamp': time.time()}
        job_logs[job_id].append(log_entry)
        
        # Step 1: Get basic customer information
        def vendor_site_callback(site_metrics):
            # Update job metrics with vendor site metrics
            if 'metrics' not in job_results[job_id]:
                job_results[job_id]['metrics'] = {}
            
            # Map vendor site metrics to job metrics
            job_metrics = job_results[job_id]['metrics']
            job_metrics['pages_checked'] = site_metrics.get('pages_checked', 0)
            job_metrics['customer_links_found'] = site_metrics.get('unique_customer_pages', site_metrics.get('customer_links_found', 0))
            
            # Update progress based on vendor site status
            status = site_metrics.get('status', '')
            message = f"Processing vendor site..."
            
            if status == 'vendor_site_started':
                message = f"Starting vendor site analysis..."
            elif status == 'vendor_site_domain_generated':
                message = f"Generated domain for {vendor_name}: {site_metrics.get('generated_domain', '')}"
            elif status == 'vendor_site_requesting':
                message = f"Accessing vendor website: {site_metrics.get('current_url', '')}"
            elif status == 'vendor_site_loaded':
                message = f"Successfully loaded vendor website ({site_metrics.get('content_bytes', 0)} bytes)"
            elif status == 'vendor_site_parsing':
                message = f"Parsing vendor website content..."
            elif status == 'vendor_site_searching_links':
                message = f"Searching for customer pages... Found {site_metrics.get('customer_links_found', 0)} links"
            elif status == 'vendor_site_customer_pages_found':
                message = f"Found {site_metrics.get('unique_customer_pages', 0)} unique customer pages"
            elif status == 'failed':
                message = f"Error: {site_metrics.get('failure_reason', 'Unknown error')}"
            
            # Update progress
            progress_step = min(40, 10 + site_metrics.get('customer_links_found', 0) * 2)
            job_results[job_id]['progress'] = {
                'step': progress_step,
                'message': message
            }
            
            # Add log entry for significant events
            log_entry = None
            if status == 'vendor_site_domain_generated':
                log_entry = {'type': 'info', 'message': f"Generated domain: {site_metrics.get('generated_domain', '')}"}
            elif status == 'vendor_site_loaded':
                log_entry = {'type': 'info', 'message': f"Loaded vendor website for {vendor_name}"}
            elif status == 'vendor_site_customer_pages_found' and site_metrics.get('unique_customer_pages', 0) > 0:
                log_entry = {'type': 'info', 'message': f"Found {site_metrics.get('unique_customer_pages', 0)} customer pages"}
            elif status == 'failed':
                log_entry = {'type': 'error', 'message': f"Error with vendor site: {site_metrics.get('failure_reason', 'Unknown error')}"}
            
            # Add log entry if we have one
            if log_entry:
                log_entry['timestamp'] = time.time()
                job_logs[job_id].append(log_entry)
        
        # Run vendor site scraping with callback
        vendor_data = scrape_vendor_site(vendor_name, progress_callback=vendor_site_callback)
        
        # Update progress after vendor site scraping
        job_results[job_id]['progress'] = {
            'step': 40,
            'message': f'Running parallel searches for {vendor_name}...'
        }
        
        # Log entry for parallel searches
        log_entry = {'type': 'info', 'message': f"Running parallel searches for {vendor_name}...", 'timestamp': time.time()}
        job_logs[job_id].append(log_entry)
        
        # Create a common status update function for all scrapers
        def enhanced_search_callback(metrics):
            # Update metrics
            if 'metrics' not in job_results[job_id]:
                job_results[job_id]['metrics'] = {}
            job_results[job_id]['metrics'].update(metrics.copy() if metrics else {})
            
            # Update status based on metrics
            status = metrics.get('status', '')
            job_results[job_id]['status'] = status if status != 'complete' else 'running'
            
            # Generate appropriate message
            message = "Processing..."
            if status == 'generating_domain':
                message = f"Generating domain for {vendor_name}..."
            elif status == 'accessing_vendor_site':
                message = f"Accessing website for {vendor_name}..."
            elif status == 'finding_customer_pages':
                message = f"Searching for customer pages..."
            elif status == 'analyzing_main_page':
                message = f"Analyzing main page content..."
            elif status == 'analyzing_customer_pages':
                page_index = metrics.get('current_customer_page_index', 0)
                total_pages = metrics.get('total_customer_pages', 0)
                message = f"Analyzing customer page {page_index}/{total_pages}..."
            elif status == 'analyzing_page_content':
                message = f"Processing content from {metrics.get('current_page', '')}..."
            elif status == 'processing_results':
                message = f"Processing results... Found {metrics.get('companies_found', 0)} companies so far"
            elif status == 'complete':
                message = f"Enhanced search complete! Found {metrics.get('companies_found', 0)} companies."
            elif status == 'error' or status.startswith('error'):
                message = f"Error: {metrics.get('error_message', 'Unknown error occurred')}"
            
            # Update progress - Grok search takes 40-60% of progress bar
            progress_step = 40
            if status == 'complete':
                progress_step = 60
            elif status.startswith('error'):
                progress_step = 60
            elif 'companies_found' in metrics and 'target_count' in metrics and metrics['target_count'] > 0:
                companies_ratio = min(1.0, metrics['companies_found'] / metrics['target_count'])
                progress_step = 40 + int(companies_ratio * 20)
            
            # Don't decrease progress
            current_progress = job_results[job_id]['progress'].get('step', 0)
            if progress_step > current_progress:
                job_results[job_id]['progress'] = {
                    'step': progress_step,
                    'message': message
                }
            
            # Add log entry if needed
            log_entry = None
            if status == 'generating_domain':
                log_entry = {'type': 'info', 'message': f"Generating domain for {vendor_name}..."}
            elif status == 'accessing_vendor_site':
                domain = metrics.get('current_page', 'unknown domain')
                log_entry = {'type': 'info', 'message': f"Accessing vendor site: {domain}"}
            elif status == 'finding_customer_pages':
                log_entry = {'type': 'info', 'message': "Searching for customer pages..."}
            elif status == 'analyzing_main_page':
                log_entry = {'type': 'info', 'message': "Analyzing main page content with Grok..."}
            elif status == 'analyzing_customer_pages':
                page_index = metrics.get('current_customer_page_index', 0)
                total_pages = metrics.get('total_customer_pages', 0)
                log_entry = {'type': 'info', 'message': f"Analyzing customer page {page_index}/{total_pages}..."}
            elif status == 'analyzing_page_content':
                page = metrics.get('current_page', 'unknown page')
                log_entry = {'type': 'info', 'message': f"Extracting companies from {page}"}
            elif status == 'processing_results':
                companies_found = metrics.get('companies_found', 0)
                log_entry = {'type': 'success', 'message': f"Enhanced search: found {companies_found} companies so far"}
            elif status == 'complete':
                companies_found = metrics.get('companies_found', 0)
                unique_companies = metrics.get('unique_companies_count', 0) or metrics.get('unique_companies', 0)
                log_entry = {'type': 'success', 'message': f"Enhanced search complete! Found {companies_found} companies, {unique_companies} unique."}
            elif status.startswith('error') or status == 'failed':
                error_msg = metrics.get('error_message', 'Unknown error')
                log_entry = {'type': 'error', 'message': f"Enhanced search error: {error_msg}"}
            
            # Add timestamp and save the log entry if we created one
            if log_entry:
                log_entry['timestamp'] = time.time()
                job_logs[job_id].append(log_entry)
        
        # Create status callback for FeaturedCustomers
        def featured_customers_callback(metrics):
            # Update metrics
            if 'metrics' not in job_results[job_id]:
                job_results[job_id]['metrics'] = {}
            
            # Store FeaturedCustomers metrics in a separate section
            if 'featured_customers' not in job_results[job_id]['metrics']:
                job_results[job_id]['metrics']['featured_customers'] = {}
            
            job_results[job_id]['metrics']['featured_customers'].update(metrics.copy() if metrics else {})
            
            # Update status based on metrics
            status = metrics.get('status', '')
            if status == 'complete':
                # Don't change overall job status when this particular search completes
                pass
            elif status == 'error' or status.startswith('error') or status == 'failed':
                # Only update status for errors
                job_results[job_id]['status'] = 'running'  # Keep running even if this part fails
            
            # Add log entry for significant events
            log_entry = None
            if status == 'featured_customers_started':
                log_entry = {'type': 'info', 'message': f"Starting FeaturedCustomers search for {vendor_name}..."}
            elif status == 'featured_customers_accessing_profile':
                profile_url = metrics.get('profile_url', '')
                if profile_url:
                    log_entry = {'type': 'info', 'message': f"Found vendor profile on FeaturedCustomers"}
            elif status == 'featured_customers_found' and metrics.get('customers_found', 0) > 0 and metrics.get('customers_found', 0) % 5 == 0:
                # Log every 5 customers found
                customers_found = metrics.get('customers_found', 0)
                log_entry = {'type': 'success', 'message': f"FeaturedCustomers: found {customers_found} customers so far"}
            elif status == 'complete':
                customers_found = metrics.get('customers_found', 0)
                log_entry = {'type': 'success', 'message': f"FeaturedCustomers search complete! Found {customers_found} customers."}
            elif status == 'error' or status.startswith('error') or status == 'failed':
                error_msg = metrics.get('error_message', metrics.get('failure_reason', 'Unknown error'))
                log_entry = {'type': 'error', 'message': f"FeaturedCustomers error: {error_msg}"}
            
            # Add timestamp and save the log entry if we created one
            if log_entry:
                log_entry['timestamp'] = time.time()
                job_logs[job_id].append(log_entry)
        
        # Define callbacks for other scrapers...
        # (Omitted for brevity - copy implementations from app.py for Google search, TrustRadius, etc.)
         
        # Log entries for starting parallel searches
        log_entry = {'type': 'info', 'message': f"Starting enhanced search with Grok for {vendor_name}...", 'timestamp': time.time()}
        job_logs[job_id].append(log_entry)
        
        log_entry = {'type': 'info', 'message': f"Starting FeaturedCustomers search for {vendor_name}...", 'timestamp': time.time()}
        job_logs[job_id].append(log_entry)
        
        log_entry = {'type': 'info', 'message': f"Starting Google search for {vendor_name}...", 'timestamp': time.time()}
        job_logs[job_id].append(log_entry)
        
        log_entry = {'type': 'info', 'message': f"Starting TrustRadius search for {vendor_name}...", 'timestamp': time.time()}
        job_logs[job_id].append(log_entry)
        
        log_entry = {'type': 'info', 'message': f"Starting PeerSpot search for {vendor_name}...", 'timestamp': time.time()}
        job_logs[job_id].append(log_entry)
        
        log_entry = {'type': 'info', 'message': f"Starting BuiltWith search for {vendor_name}...", 'timestamp': time.time()}
        job_logs[job_id].append(log_entry)
        
        log_entry = {'type': 'info', 'message': f"Starting PublicWWW search for {vendor_name}...", 'timestamp': time.time()}
        job_logs[job_id].append(log_entry)
        
        # Run all searches in parallel (in a worker dyno we can take as long as needed)
        # Do the enhanced search with our callback
        enhanced_data = enhanced_vendor_search(vendor_name, max_results=max_results, status_callback=enhanced_search_callback)
        
        # Do the FeaturedCustomers search with our callback
        featured_data = scrape_featured_customers(vendor_name, max_results=max_results, status_callback=featured_customers_callback)
        
        # Do the Google search 
        google_data = search_google(vendor_name)
        
        # Do the TrustRadius search 
        trust_radius_data = scrape_trust_radius(vendor_name, max_results=max_results)
        
        # Do the PeerSpot search 
        peerspot_data = scrape_peerspot(vendor_name, max_results=max_results)
        
        # Do the BuiltWith search 
        builtwith_data = scrape_builtwith(vendor_name, max_results=max_results)
        
        # Do the PublicWWW search 
        publicwww_data = scrape_publicwww(vendor_name, max_results=max_results)
        
        # Extract results and metrics from enhanced search
        if hasattr(enhanced_data, 'results') and hasattr(enhanced_data, 'metrics'):
            results_data = enhanced_data.results
            metrics = enhanced_data.metrics
            worker_logger.info(f"Enhanced search metrics: {metrics}")
            if 'metrics' not in job_results[job_id]:
                job_results[job_id]['metrics'] = {}
            job_results[job_id]['metrics'].update(metrics)
        else:
            results_data = enhanced_data
            worker_logger.info("No metrics available from enhanced search")
        
        # Update job progress
        job_results[job_id]['progress'] = {
            'step': 80, 
            'message': 'Combining results from all sources...'
        }
        
        # Log entry for combining results
        log_entry = {'type': 'info', 
                   'message': f"Combining results from vendor site, " +
                             f"enhanced search, " +
                             f"FeaturedCustomers, " +
                             f"Google search, " +
                             f"TrustRadius, " +
                             f"PeerSpot, " +
                             f"BuiltWith, " +
                             f"PublicWWW, " +
                             f"Enlyft, " +
                             f"NerdyData, and " +
                             f"AppsRunTheWorld",
                   'timestamp': time.time()}
        job_logs[job_id].append(log_entry)
        
        # Combine results from all sources
        worker_logger.info(f"Combining results from vendor site, " +
                       f"enhanced search, " +
                       f"FeaturedCustomers, " +
                       f"Google search, " +
                       f"TrustRadius, " +
                       f"PeerSpot, " +
                       f"BuiltWith, " +
                       f"PublicWWW, " +
                       f"Enlyft, " +
                       f"NerdyData, and " +
                       f"AppsRunTheWorld")
        
        # Start with vendor data
        combined_data = vendor_data.copy()
        
        # Add enhanced data, avoiding duplicates
        existing_names = {item.get('name', '').lower() for item in vendor_data}
        for item in results_data:
            if item.get('name', '').lower() not in existing_names:
                combined_data.append(item)
                existing_names.add(item.get('name', '').lower())
        
        # Add FeaturedCustomers data, avoiding duplicates
        for item in featured_data:
            if item.get('name', '').lower() not in existing_names:
                combined_data.append(item)
                existing_names.add(item.get('name', '').lower())
        
        # Add Google search data, avoiding duplicates
        for item in google_data:
            if item.get('name', '').lower() not in existing_names:
                combined_data.append(item)
                existing_names.add(item.get('name', '').lower())
                
        # Add TrustRadius data, avoiding duplicates
        for item in trust_radius_data:
            if item.get('name', '').lower() not in existing_names:
                combined_data.append(item)
                existing_names.add(item.get('name', '').lower())
                
        # Add PeerSpot data, avoiding duplicates
        for item in peerspot_data:
            if item.get('name', '').lower() not in existing_names:
                combined_data.append(item)
                existing_names.add(item.get('name', '').lower())
        
        # Add BuiltWith data, avoiding duplicates
        for item in builtwith_data:
            if item.get('name', '').lower() not in existing_names:
                combined_data.append(item)
                existing_names.add(item.get('name', '').lower())
        
        # Add PublicWWW data, avoiding duplicates
        for item in publicwww_data:
            if item.get('name', '').lower() not in existing_names:
                combined_data.append(item)
                existing_names.add(item.get('name', '').lower())
        
        # Format the data for the results template
        formatted_results = []
        
        for item in combined_data:
            # Get the URL from the item
            url = item.get('url', None)
            
            # Skip items without a valid URL
            if not url:
                continue
                
            formatted_results.append({
                'competitor': vendor_name,
                'customer_name': item.get('name', 'Unknown'),
                'customer_url': url
            })
        
        # Limit final results to the user-specified max_results if we have too many
        if len(formatted_results) > max_results:
            worker_logger.info(f"Limiting final results to requested amount")
            formatted_results = formatted_results[:max_results]
        
        # This function would need to be implemented if you're using it
        # Generate additional suggestions with Grok if we have fewer results than requested
        # if len(formatted_results) < max_results:
        #     worker_logger.info(f"Generating additional suggestions to reach target count...")
        #     additional_results = generate_additional_suggestions(vendor_name, formatted_results, max_results - len(formatted_results))
        #     
        #     # Add a source field to the original results for clarity
        #     for result in formatted_results:
        #         if "source" not in result:
        #             result["source"] = "Scraped"
        #     
        #     # Add the additional results to our formatted results
        #     formatted_results.extend(additional_results)
        #     
        #     worker_logger.info(f"Added AI-generated suggestions to results")
        #     
        #     # Log entry for the AI generation
        #     log_entry = {
        #         'type': 'info',
        #         'message': f"Generated additional potential customers with AI assistance",
        #         'timestamp': time.time()
        #     }
        #     job_logs[job_id].append(log_entry)
        
        worker_logger.info(f"Found customers for {vendor_name}")
        
        # Update job status with final results
        job_results[job_id].update({
            'status': 'completed',
            'results': formatted_results,
            'end_time': time.time(),
            'duration': time.time() - job_results[job_id]['start_time']
        })
        
        # Add final log entry
        log_entry = {
            'type': 'success', 
            'message': f"Search complete! Results found for {vendor_name}.",
            'timestamp': time.time()
        }
        job_logs[job_id].append(log_entry)
        
        return job_results[job_id]
        
    except Exception as e:
        worker_logger.exception(f"Error processing job {job_id}: {str(e)}")
        job_results[job_id].update({
            'status': 'failed',
            'error': str(e),
            'end_time': time.time(),
            'duration': time.time() - job_results[job_id]['start_time']
        })
        
        # Add error log entry
        log_entry = {
            'type': 'error', 
            'message': f"Error: {str(e)}",
            'timestamp': time.time()
        }
        job_logs[job_id].append(log_entry)
        
        return job_results[job_id]

def fetch_job_result(job_id):
    """
    Get the current status and results for a job.
    
    Args:
        job_id: The ID of the job to check
        
    Returns:
        Dict containing job status, progress, and results if complete
    """
    if job_id in job_results:
        result = job_results[job_id].copy()
        
        # Add logs if available
        if job_id in job_logs:
            # Return most recent 50 logs
            result['logs'] = job_logs[job_id][-50:]
            
        return result
    else:
        return {
            'status': 'not_found',
            'error': f"Job {job_id} not found"
        }

def cleanup_old_jobs():
    """
    Periodically cleanup old jobs to prevent memory leaks.
    
    This removes completed jobs that are older than 1 hour.
    """
    now = time.time()
    to_remove = []
    
    for job_id, job in job_results.items():
        # If job is completed or failed and is older than 1 hour
        if (job.get('status') in ['completed', 'failed'] and 
            job.get('end_time') and 
            now - job.get('end_time') > 3600):
            to_remove.append(job_id)
    
    # Remove old jobs
    for job_id in to_remove:
        del job_results[job_id]
        if job_id in job_logs:
            del job_logs[job_id]
            
    worker_logger.info(f"Cleaned up {len(to_remove)} old jobs")

# Main worker loop
if __name__ == "__main__":
    try:
        worker_logger.info("Worker process started")
        
        # Create a cleanup thread that runs every 15 minutes
        def cleanup_thread_func():
            while True:
                time.sleep(900)  # 15 minutes
                try:
                    cleanup_old_jobs()
                except Exception as e:
                    worker_logger.error(f"Error in cleanup thread: {str(e)}")
        
        cleanup_thread = threading.Thread(target=cleanup_thread_func, daemon=True)
        cleanup_thread.start()
        
        # In a real production app, this would pull from Redis or another queue
        # For now, it's just a placeholder that runs forever
        while True:
            time.sleep(10)  # Check for jobs every 10 seconds
            worker_logger.info("Worker checking for jobs...")
            
    except Exception as e:
        worker_logger.exception(f"Unhandled exception in worker process: {str(e)}")