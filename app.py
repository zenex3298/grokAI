import os
import time
import threading
import queue
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from src.scrapers.vendor_site import scrape_vendor_site
from src.scrapers.enhanced_search import enhanced_vendor_search
from src.scrapers.featured_customers import scrape_featured_customers
from src.scrapers.search_engines import search_google
from src.scrapers.trust_radius import scrape_trust_radius
from src.utils.data_validator import validate_combined_data
from src.utils.logger import setup_logging, get_logger, LogComponent, set_context

# Load environment variables
load_dotenv()

# Configure logging
logger = setup_logging()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev_secret_key')

# Initialize job tracking structures
app.job_results = {}
app.job_logs = {}
app.job_queue = queue.Queue()  # Queue for background processing

# Worker thread function to process jobs in background
def background_worker():
    app_logger = get_logger(LogComponent.APP)
    app_logger.info("Background worker thread started")
    
    while True:
        try:
            # Get a job from the queue (blocks until a job is available)
            job_id, vendor_name = app.job_queue.get()
            app_logger.info(f"Processing job {job_id} for vendor {vendor_name}")
            
            # Mark the job as being processed
            app.job_results[job_id]['status'] = 'processing'
            
            # Process vendor site scraping
            try:
                # Add initial log
                log_entry = {'type': 'info', 'message': f"Starting analysis for {vendor_name}...", 'timestamp': time.time()}
                app.job_logs[job_id].append(log_entry)
                
                # Update progress
                app.job_results[job_id]['progress'] = {
                    'step': 20,
                    'message': f'Searching vendor website for {vendor_name}...'
                }
                
                # Log entry for vendor site search
                log_entry = {'type': 'info', 'message': f"Searching vendor website for {vendor_name}...", 'timestamp': time.time()}
                app.job_logs[job_id].append(log_entry)
                
                # Step 1: Get basic customer information with status callback
                def vendor_site_callback(site_metrics):
                    # Update job metrics with vendor site metrics
                    if 'metrics' not in app.job_results[job_id]:
                        app.job_results[job_id]['metrics'] = {}
                    
                    # Map vendor site metrics to job metrics
                    job_metrics = app.job_results[job_id]['metrics']
                    job_metrics['pages_checked'] = site_metrics.get('pages_checked', 0)
                    # Use unique_customer_pages instead of customer_links_found for consistency
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
                    app.job_results[job_id]['progress'] = {
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
                        app.job_logs[job_id].append(log_entry)
                
                # Run vendor site scraping with callback
                vendor_data = scrape_vendor_site(vendor_name, progress_callback=vendor_site_callback)
                
                # Update progress after vendor site scraping
                app.job_results[job_id]['progress'] = {
                    'step': 40,
                    'message': f'Running parallel searches for {vendor_name}...'
                }
                
                # Log entry for parallel searches
                log_entry = {'type': 'info', 'message': f"Running parallel searches for {vendor_name}...", 'timestamp': time.time()}
                app.job_logs[job_id].append(log_entry)
                
                # Create a common status update function for all scrapers
                def enhanced_search_callback(metrics):
                    # Update metrics
                    if 'metrics' not in app.job_results[job_id]:
                        app.job_results[job_id]['metrics'] = {}
                    app.job_results[job_id]['metrics'].update(metrics.copy() if metrics else {})
                    
                    # Update status based on metrics
                    status = metrics.get('status', '')
                    app.job_results[job_id]['status'] = status if status != 'complete' else 'running'
                    
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
                    current_progress = app.job_results[job_id]['progress'].get('step', 0)
                    if progress_step > current_progress:
                        app.job_results[job_id]['progress'] = {
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
                        app.job_logs[job_id].append(log_entry)
                
                # Create status callback for FeaturedCustomers
                def featured_customers_callback(metrics):
                    # Update metrics
                    if 'metrics' not in app.job_results[job_id]:
                        app.job_results[job_id]['metrics'] = {}
                    
                    # Store FeaturedCustomers metrics in a separate section
                    if 'featured_customers' not in app.job_results[job_id]['metrics']:
                        app.job_results[job_id]['metrics']['featured_customers'] = {}
                    
                    app.job_results[job_id]['metrics']['featured_customers'].update(metrics.copy() if metrics else {})
                    
                    # Update status based on metrics
                    status = metrics.get('status', '')
                    if status == 'complete':
                        # Don't change overall job status when this particular search completes
                        pass
                    elif status == 'error' or status.startswith('error') or status == 'failed':
                        # Only update status for errors
                        app.job_results[job_id]['status'] = 'running'  # Keep running even if this part fails
                    
                    # Generate appropriate message
                    message = "Processing FeaturedCustomers..."
                    if status == 'featured_customers_started':
                        message = f"Starting FeaturedCustomers search for {vendor_name}..."
                    elif status == 'featured_customers_searching':
                        message = f"Searching FeaturedCustomers for {vendor_name}..."
                    elif status == 'featured_customers_parsing_search':
                        message = f"Parsing FeaturedCustomers search results..."
                    elif status == 'featured_customers_accessing_profile':
                        message = f"Accessing vendor profile on FeaturedCustomers..."
                    elif status == 'featured_customers_parsing_profile':
                        message = f"Analyzing vendor profile on FeaturedCustomers..."
                    elif status == 'featured_customers_processing_section':
                        section_index = metrics.get('current_section', 0)
                        total_sections = metrics.get('total_sections', 0)
                        message = f"Processing customer section {section_index}/{total_sections} on FeaturedCustomers..."
                    elif status == 'featured_customers_found':
                        message = f"Found {metrics.get('customers_found', 0)} customers on FeaturedCustomers..."
                    elif status == 'complete':
                        message = f"FeaturedCustomers search complete! Found {metrics.get('customers_found', 0)} customers."
                    elif status == 'error' or status.startswith('error') or status == 'failed':
                        message = f"FeaturedCustomers error: {metrics.get('error_message', 'Unknown error')}"
                    
                    # Calculate progress - FeaturedCustomers search takes 40-60% of progress bar
                    progress_step = 40
                    if status == 'complete':
                        progress_step = 60
                    elif status.startswith('error') or status == 'failed':
                        progress_step = 60
                    elif 'customers_found' in metrics and 'target_count' in metrics and metrics['target_count'] > 0:
                        customers_ratio = min(1.0, metrics['customers_found'] / metrics['target_count'])
                        progress_step = 40 + int(customers_ratio * 20)
                    
                    # Don't decrease progress
                    current_progress = app.job_results[job_id]['progress'].get('step', 0)
                    if progress_step > current_progress:
                        app.job_results[job_id]['progress'] = {
                            'step': progress_step,
                            'message': message
                        }
                    
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
                        app.job_logs[job_id].append(log_entry)
                
                # Create status callback for Google Search
                def google_search_callback(metrics):
                    # Update metrics
                    if 'metrics' not in app.job_results[job_id]:
                        app.job_results[job_id]['metrics'] = {}
                    
                    # Store Google Search metrics in a separate section
                    if 'google_search' not in app.job_results[job_id]['metrics']:
                        app.job_results[job_id]['metrics']['google_search'] = {}
                    
                    app.job_results[job_id]['metrics']['google_search'].update(metrics.copy() if metrics else {})
                    
                    # Update status based on metrics
                    status = metrics.get('status', '')
                    if status == 'success' or status == 'complete':
                        # Don't change overall job status when this particular search completes
                        pass
                    elif status == 'error' or status == 'failed':
                        # Only update status for errors
                        app.job_results[job_id]['status'] = 'running'  # Keep running even if this part fails
                    
                    # Generate appropriate message
                    message = "Processing Google Search..."
                    if status == 'started':
                        message = f"Starting Google search for {vendor_name}..."
                    elif status == 'fallback_basic':
                        message = f"Using basic Google search for {vendor_name}..."
                    elif 'queries_run' in metrics and 'queries_successful' in metrics:
                        message = f"Running Google searches... {metrics.get('queries_successful', 0)}/{metrics.get('queries_run', 0)} complete"
                    elif status == 'success':
                        message = f"Google search complete! Found {metrics.get('unique_customers', 0)} customers."
                    elif status == 'empty':
                        message = f"Google search complete but found no results."
                    elif status == 'error' or status == 'failed':
                        message = f"Google search error: {metrics.get('error_message', 'Unknown error')}"
                    
                    # Calculate progress - Google search takes 40-60% of progress bar
                    progress_step = 40
                    if status == 'success' or status == 'complete' or status == 'empty':
                        progress_step = 60
                    elif status == 'error' or status == 'failed':
                        progress_step = 60
                    elif 'queries_run' in metrics and 'queries_successful' in metrics and len(metrics.get('query_metrics', [])) > 0:
                        queries_ratio = min(1.0, metrics['queries_run'] / len(metrics.get('query_metrics', [])))
                        progress_step = 40 + int(queries_ratio * 20)
                    
                    # Don't decrease progress
                    current_progress = app.job_results[job_id]['progress'].get('step', 0)
                    if progress_step > current_progress:
                        app.job_results[job_id]['progress'] = {
                            'step': progress_step,
                            'message': message
                        }
                    
                    # Add log entry for significant events
                    log_entry = None
                    if status == 'started':
                        log_entry = {'type': 'info', 'message': f"Starting Google search for {vendor_name}..."}
                    elif status == 'fallback_basic':
                        log_entry = {'type': 'info', 'message': f"Using basic Google search for {vendor_name}..."}
                    elif 'customers_found' in metrics and metrics.get('customers_found', 0) > 0 and metrics.get('customers_found', 0) % 5 == 0:
                        # Log every 5 customers found
                        customers_found = metrics.get('customers_found', 0)
                        log_entry = {'type': 'success', 'message': f"Google Search: found {customers_found} customers so far"}
                    elif status == 'success' or status == 'complete':
                        customers_found = metrics.get('unique_customers', 0)
                        log_entry = {'type': 'success', 'message': f"Google search complete! Found {customers_found} unique customers."}
                    elif status == 'error' or status == 'failed':
                        error_msg = metrics.get('error_message', 'Unknown error')
                        log_entry = {'type': 'error', 'message': f"Google search error: {error_msg}"}
                    
                    # Add timestamp and save the log entry if we created one
                    if log_entry:
                        log_entry['timestamp'] = time.time()
                        app.job_logs[job_id].append(log_entry)
                
                # Log entries for starting parallel searches
                log_entry = {'type': 'info', 'message': f"Starting enhanced search with Grok for {vendor_name}...", 'timestamp': time.time()}
                app.job_logs[job_id].append(log_entry)
                
                log_entry = {'type': 'info', 'message': f"Starting FeaturedCustomers search for {vendor_name}...", 'timestamp': time.time()}
                app.job_logs[job_id].append(log_entry)
                
                log_entry = {'type': 'info', 'message': f"Starting Google search for {vendor_name}...", 'timestamp': time.time()}
                app.job_logs[job_id].append(log_entry)
                
                log_entry = {'type': 'info', 'message': f"Starting TrustRadius search for {vendor_name}...", 'timestamp': time.time()}
                app.job_logs[job_id].append(log_entry)
                
                # Create status callback for TrustRadius
                def trust_radius_callback(metrics):
                    # Update metrics
                    if 'metrics' not in app.job_results[job_id]:
                        app.job_results[job_id]['metrics'] = {}
                    
                    # Store TrustRadius metrics in a separate section
                    if 'trust_radius' not in app.job_results[job_id]['metrics']:
                        app.job_results[job_id]['metrics']['trust_radius'] = {}
                    
                    app.job_results[job_id]['metrics']['trust_radius'].update(metrics.copy() if metrics else {})
                    
                    # Update status based on metrics
                    status = metrics.get('status', '')
                    if status == 'complete':
                        # Don't change overall job status when this particular search completes
                        pass
                    elif status == 'error' or status.startswith('error') or status == 'failed':
                        # Only update status for errors
                        app.job_results[job_id]['status'] = 'running'  # Keep running even if this part fails
                    
                    # Generate appropriate message
                    message = "Processing TrustRadius..."
                    if status == 'trust_radius_started':
                        message = f"Starting TrustRadius search for {vendor_name}..."
                    elif status == 'trust_radius_searching':
                        message = f"Searching TrustRadius for {vendor_name}..."
                    elif status == 'trust_radius_parsing_search':
                        message = f"Parsing TrustRadius search results..."
                    elif status == 'trust_radius_accessing_profile':
                        message = f"Accessing vendor profile on TrustRadius..."
                    elif status == 'trust_radius_analyzing':
                        message = f"Analyzing TrustRadius content..."
                    elif status == 'trust_radius_grok_PREPARING':
                        message = f"Preparing TrustRadius data for analysis..."
                    elif status == 'trust_radius_grok_API_CALL':
                        message = f"Sending TrustRadius data to Grok..."
                    elif status == 'trust_radius_customer_found' or status == 'trust_radius_grok_FINALIZING':
                        message = f"Found {metrics.get('customers_found', 0)} customers on TrustRadius..."
                    elif status == 'complete':
                        message = f"TrustRadius search complete! Found {metrics.get('customers_found', 0)} customers."
                    elif status == 'error' or status.startswith('error') or status == 'failed':
                        message = f"TrustRadius error: {metrics.get('error_message', metrics.get('failure_reason', 'Unknown error'))}"
                    
                    # Calculate progress - TrustRadius search takes 40-60% of progress bar
                    progress_step = 40
                    if status == 'complete':
                        progress_step = 60
                    elif status.startswith('error') or status == 'failed':
                        progress_step = 60
                    elif 'customers_found' in metrics and 'target_count' in metrics and metrics['target_count'] > 0:
                        customers_ratio = min(1.0, metrics['customers_found'] / metrics['target_count'])
                        progress_step = 40 + int(customers_ratio * 20)
                    
                    # Don't decrease progress
                    current_progress = app.job_results[job_id]['progress'].get('step', 0)
                    if progress_step > current_progress:
                        app.job_results[job_id]['progress'] = {
                            'step': progress_step,
                            'message': message
                        }
                    
                    # Add log entry for significant events
                    log_entry = None
                    if status == 'trust_radius_started':
                        log_entry = {'type': 'info', 'message': f"Starting TrustRadius search for {vendor_name}..."}
                    elif status == 'trust_radius_accessing_profile':
                        profile_url = metrics.get('profile_url', '')
                        if profile_url:
                            log_entry = {'type': 'info', 'message': f"Found vendor profile on TrustRadius"}
                    elif status == 'trust_radius_customer_found' and metrics.get('customers_found', 0) > 0 and metrics.get('customers_found', 0) % 5 == 0:
                        # Log every 5 customers found
                        customers_found = metrics.get('customers_found', 0)
                        log_entry = {'type': 'success', 'message': f"TrustRadius: found {customers_found} customers so far"}
                    elif status == 'complete':
                        customers_found = metrics.get('customers_found', 0)
                        log_entry = {'type': 'success', 'message': f"TrustRadius search complete! Found {customers_found} customers."}
                    elif status == 'error' or status.startswith('error') or status == 'failed':
                        error_msg = metrics.get('error_message', metrics.get('failure_reason', 'Unknown error'))
                        log_entry = {'type': 'error', 'message': f"TrustRadius error: {error_msg}"}
                    
                    # Add timestamp and save the log entry if we created one
                    if log_entry:
                        log_entry['timestamp'] = time.time()
                        app.job_logs[job_id].append(log_entry)
                
                # Do the enhanced search with our callback
                enhanced_data = enhanced_vendor_search(vendor_name, max_results=20, status_callback=enhanced_search_callback)
                
                # Do the FeaturedCustomers search with our callback
                featured_data = scrape_featured_customers(vendor_name, max_results=20, status_callback=featured_customers_callback)
                
                # Do the Google search with our callback
                google_data = search_google(vendor_name, status_callback=google_search_callback)
                
                # Do the TrustRadius search with our callback
                trust_radius_data = scrape_trust_radius(vendor_name, max_results=20, status_callback=trust_radius_callback)
                
                # Extract results and metrics from enhanced search
                if hasattr(enhanced_data, 'results') and hasattr(enhanced_data, 'metrics'):
                    results_data = enhanced_data.results
                    metrics = enhanced_data.metrics
                    app_logger.info(f"Enhanced search metrics: {metrics}")
                    if 'metrics' not in app.job_results[job_id]:
                        app.job_results[job_id]['metrics'] = {}
                    app.job_results[job_id]['metrics'].update(metrics)
                else:
                    results_data = enhanced_data
                    app_logger.info("No metrics available from enhanced search")
                
                # Update job progress
                app.job_results[job_id]['progress'] = {
                    'step': 80, 
                    'message': 'Combining results from all sources...'
                }
                
                # Log entry for combining results
                log_entry = {'type': 'info', 
                           'message': f"Combining results from vendor site ({len(vendor_data)} items), " +
                                     f"enhanced search ({len(results_data)} items), " +
                                     f"FeaturedCustomers ({len(featured_data)} items), " +
                                     f"Google search ({len(google_data)} items), and " +
                                     f"TrustRadius ({len(trust_radius_data)} items)",
                           'timestamp': time.time()}
                app.job_logs[job_id].append(log_entry)
                
                # Combine results from all sources
                app_logger.info(f"Combining results from vendor site ({len(vendor_data)} items), " +
                               f"enhanced search ({len(results_data)} items), " +
                               f"FeaturedCustomers ({len(featured_data)} items), " +
                               f"Google search ({len(google_data)} items), and " +
                               f"TrustRadius ({len(trust_radius_data)} items)")
                
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
                
                app_logger.info(f"Found {len(formatted_results)} customers for {vendor_name}")
                
                # Update job status with final results
                app.job_results[job_id].update({
                    'status': 'completed',
                    'results': formatted_results,
                    'end_time': time.time(),
                    'duration': time.time() - app.job_results[job_id]['start_time']
                })
                
                # Add final log entry
                log_entry = {
                    'type': 'success', 
                    'message': f"Analysis complete! Found {len(formatted_results)} customers for {vendor_name}.",
                    'timestamp': time.time()
                }
                app.job_logs[job_id].append(log_entry)
                
            except Exception as e:
                app_logger.exception(f"Error processing job {job_id}: {str(e)}")
                app.job_results[job_id].update({
                    'status': 'failed',
                    'error': str(e),
                    'end_time': time.time(),
                    'duration': time.time() - app.job_results[job_id]['start_time']
                })
                
                # Add error log entry
                log_entry = {
                    'type': 'error', 
                    'message': f"Error: {str(e)}",
                    'timestamp': time.time()
                }
                app.job_logs[job_id].append(log_entry)
            
            # Mark task as done in the queue
            app.job_queue.task_done()
            
        except Exception as e:
            app_logger.exception(f"Unhandled error in background worker: {str(e)}")
            # Still mark task as done to avoid blocking the queue
            try:
                app.job_queue.task_done()
            except:
                pass

# Start the background worker thread
worker_thread = threading.Thread(target=background_worker, daemon=True)
worker_thread.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    vendor_name = request.form.get('vendor_name')
    
    if not vendor_name:
        return jsonify({'error': 'Vendor name is required'}), 400
    
    # Set request context and get app logger
    set_context(vendor_name=vendor_name, request_path='/analyze', operation='analyze_vendor')
    app_logger = get_logger(LogComponent.APP)
    
    # Log the request
    app_logger.info(f"Received request to analyze vendor: {vendor_name}")
    
    # Create a job ID for tracking
    job_id = f"{vendor_name}_{int(time.time())}"
    app_logger.info(f"Created job ID: {job_id}")
    
    # Initialize job in the job results dictionary
    app.job_results[job_id] = {
        'status': 'queued',
        'progress': {
            'step': 5,
            'message': f'Waiting to process {vendor_name}...'
        },
        'metrics': {
            'pages_checked': 0,
            'customer_links_found': 0,
            'companies_found': 0,
            'unique_companies': 0,
            'target_count': 20
        },
        'vendor_name': vendor_name,
        'start_time': time.time()
    }
    
    # Initialize logs for this job
    app.job_logs[job_id] = []
    
    # Add the job to the processing queue
    app.job_queue.put((job_id, vendor_name))
    app_logger.info(f"Added job {job_id} to processing queue")
    
    # Initial log entry
    log_entry = {
        'type': 'info',
        'message': f"Added {vendor_name} to processing queue...",
        'timestamp': time.time()
    }
    app.job_logs[job_id].append(log_entry)
    
    # Return the job ID immediately so the front end can start polling
    return render_template('results.html',
                          vendor_name=vendor_name,
                          job_id=job_id,
                          polling=True)


# Background job processing endpoint that will be called via AJAX
@app.route('/job_status/<job_id>', methods=['GET'])
def job_status(job_id):
    try:
        # Get the vendor name from the job ID (format is vendor_timestamp)
        parts = job_id.split('_')
        if len(parts) >= 2:
            vendor_name = parts[0]
        else:
            return jsonify({'status': 'error', 'error': 'Invalid job ID format'}), 400
        
        # Set request context
        set_context(vendor_name=vendor_name, request_path=f'/job_status/{job_id}', operation='check_job_status')
        app_logger = get_logger(LogComponent.APP)
        
        # Check if the job exists
        if job_id not in app.job_results:
            # This should not happen with our new implementation, but just in case
            error_msg = f"Job {job_id} not found"
            app_logger.error(error_msg)
            return jsonify({'status': 'error', 'error': error_msg}), 404
        
        # Return the current status of the job, including the most recent logs (up to 50)
        response_data = app.job_results[job_id].copy()
        
        # Add logs if available
        if job_id in app.job_logs:
            # Return most recent 50 logs
            response_data['logs'] = app.job_logs[job_id][-50:]
        
        return jsonify(response_data), 200
        
    except Exception as e:
        app_logger.exception(f"Error checking job status {job_id}: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'False') == 'True')
