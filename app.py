import os
import time
import threading
import queue
import json
import requests
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
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
from src.utils.url_validator import validate_url, log_validation_stats

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
            job_data = app.job_queue.get()
            
            # Handle both old (2-element) and new (3-element) queue formats
            if len(job_data) == 3:
                job_id, vendor_name, max_results = job_data
            else:
                job_id, vendor_name = job_data
                max_results = app.job_results[job_id].get('max_results', 20)
                
            app_logger.info(f"Processing job {job_id} for vendor {vendor_name} with max_results: {max_results}")
            
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
                
                log_entry = {'type': 'info', 'message': f"Starting PeerSpot search for {vendor_name}...", 'timestamp': time.time()}
                app.job_logs[job_id].append(log_entry)
                
                log_entry = {'type': 'info', 'message': f"Starting BuiltWith search for {vendor_name}...", 'timestamp': time.time()}
                app.job_logs[job_id].append(log_entry)
                
                log_entry = {'type': 'info', 'message': f"Starting PublicWWW search for {vendor_name}...", 'timestamp': time.time()}
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
                
                # Create status callback for PeerSpot
                def peerspot_callback(metrics):
                    # Update metrics
                    if 'metrics' not in app.job_results[job_id]:
                        app.job_results[job_id]['metrics'] = {}
                    
                    # Store PeerSpot metrics in a separate section
                    if 'peerspot' not in app.job_results[job_id]['metrics']:
                        app.job_results[job_id]['metrics']['peerspot'] = {}
                    
                    app.job_results[job_id]['metrics']['peerspot'].update(metrics.copy() if metrics else {})
                    
                    # Update status based on metrics
                    status = metrics.get('status', '')
                    if status == 'complete':
                        # Don't change overall job status when this particular search completes
                        pass
                    elif status == 'error' or status.startswith('error') or status == 'failed':
                        # Only update status for errors
                        app.job_results[job_id]['status'] = 'running'  # Keep running even if this part fails
                    
                    # Generate appropriate message
                    message = "Processing PeerSpot..."
                    if status == 'peerspot_started':
                        message = f"Starting PeerSpot search for {vendor_name}..."
                    elif status == 'peerspot_searching':
                        message = f"Searching PeerSpot for {vendor_name}..."
                    elif status == 'peerspot_parsing_search':
                        message = f"Parsing PeerSpot search results..."
                    elif status == 'peerspot_accessing_profile':
                        message = f"Accessing vendor profile on PeerSpot..."
                    elif status == 'peerspot_extracting':
                        message = f"Extracting data from PeerSpot..."
                    elif status == 'peerspot_analyzing':
                        message = f"Analyzing PeerSpot content..."
                    elif status == 'peerspot_grok_PREPARING':
                        message = f"Preparing PeerSpot data for analysis..."
                    elif status == 'peerspot_grok_API_CALL':
                        message = f"Sending PeerSpot data to Grok..."
                    elif status == 'peerspot_customer_found' or status == 'peerspot_grok_FINALIZING':
                        message = f"Found {metrics.get('customers_found', 0)} customers on PeerSpot..."
                    elif status == 'complete':
                        message = f"PeerSpot search complete! Found {metrics.get('customers_found', 0)} customers."
                    elif status == 'error' or status.startswith('error') or status == 'failed':
                        message = f"PeerSpot error: {metrics.get('error_message', metrics.get('failure_reason', 'Unknown error'))}"
                    
                    # Calculate progress - PeerSpot search takes 40-60% of progress bar
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
                    if status == 'peerspot_started':
                        log_entry = {'type': 'info', 'message': f"Starting PeerSpot search for {vendor_name}..."}
                    elif status == 'peerspot_accessing_profile':
                        profile_url = metrics.get('profile_url', '')
                        if profile_url:
                            log_entry = {'type': 'info', 'message': f"Found vendor profile on PeerSpot"}
                    elif status == 'peerspot_customer_found' and metrics.get('customers_found', 0) > 0 and metrics.get('customers_found', 0) % 5 == 0:
                        # Log every 5 customers found
                        customers_found = metrics.get('customers_found', 0)
                        log_entry = {'type': 'success', 'message': f"PeerSpot: found {customers_found} customers so far"}
                    elif status == 'complete':
                        customers_found = metrics.get('customers_found', 0)
                        log_entry = {'type': 'success', 'message': f"PeerSpot search complete! Found {customers_found} customers."}
                    elif status == 'error' or status.startswith('error') or status == 'failed':
                        error_msg = metrics.get('error_message', metrics.get('failure_reason', 'Unknown error'))
                        log_entry = {'type': 'error', 'message': f"PeerSpot error: {error_msg}"}
                    
                    # Add timestamp and save the log entry if we created one
                    if log_entry:
                        log_entry['timestamp'] = time.time()
                        app.job_logs[job_id].append(log_entry)
                
                # Create status callback for BuiltWith
                def builtwith_callback(metrics):
                    # Update metrics
                    if 'metrics' not in app.job_results[job_id]:
                        app.job_results[job_id]['metrics'] = {}
                    
                    # Store BuiltWith metrics in a separate section
                    if 'builtwith' not in app.job_results[job_id]['metrics']:
                        app.job_results[job_id]['metrics']['builtwith'] = {}
                    
                    app.job_results[job_id]['metrics']['builtwith'].update(metrics.copy() if metrics else {})
                    
                    # Update status based on metrics
                    status = metrics.get('status', '')
                    if status == 'complete':
                        # Don't change overall job status when this particular search completes
                        pass
                    elif status == 'error' or status.startswith('error') or status == 'failed':
                        # Only update status for errors
                        app.job_results[job_id]['status'] = 'running'  # Keep running even if this part fails
                    
                    # Generate appropriate message
                    message = "Processing BuiltWith..."
                    if status == 'builtwith_started':
                        message = f"Starting BuiltWith search for {vendor_name}..."
                    elif status == 'builtwith_searching':
                        message = f"Searching BuiltWith for {vendor_name}..."
                    elif status == 'builtwith_parsing_search':
                        message = f"Parsing BuiltWith search results..."
                    elif status == 'builtwith_analyzing':
                        message = f"Analyzing BuiltWith content..."
                    elif status == 'builtwith_grok_PREPARING':
                        message = f"Preparing BuiltWith data for analysis..."
                    elif status == 'builtwith_grok_API_CALL':
                        message = f"Sending BuiltWith data to Grok..."
                    elif status == 'builtwith_customer_found' or status == 'builtwith_grok_FINALIZING':
                        message = f"Found {metrics.get('customers_found', 0)} customers on BuiltWith..."
                    elif status == 'complete':
                        message = f"BuiltWith search complete! Found {metrics.get('customers_found', 0)} customers."
                    elif status == 'error' or status.startswith('error') or status == 'failed':
                        message = f"BuiltWith error: {metrics.get('error_message', metrics.get('failure_reason', 'Unknown error'))}"
                    
                    # Calculate progress - BuiltWith search takes 40-60% of progress bar
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
                    if status == 'builtwith_started':
                        log_entry = {'type': 'info', 'message': f"Starting BuiltWith search for {vendor_name}..."}
                    elif status == 'builtwith_customer_found' and metrics.get('customers_found', 0) > 0 and metrics.get('customers_found', 0) % 5 == 0:
                        # Log every 5 customers found
                        customers_found = metrics.get('customers_found', 0)
                        log_entry = {'type': 'success', 'message': f"BuiltWith: found {customers_found} customers so far"}
                    elif status == 'complete':
                        customers_found = metrics.get('customers_found', 0)
                        log_entry = {'type': 'success', 'message': f"BuiltWith search complete! Found {customers_found} customers."}
                    elif status == 'error' or status.startswith('error') or status == 'failed':
                        error_msg = metrics.get('error_message', metrics.get('failure_reason', 'Unknown error'))
                        log_entry = {'type': 'error', 'message': f"BuiltWith error: {error_msg}"}
                    
                    # Add timestamp and save the log entry if we created one
                    if log_entry:
                        log_entry['timestamp'] = time.time()
                        app.job_logs[job_id].append(log_entry)
                        
                # Create status callback for PublicWWW
                def publicwww_callback(metrics):
                    # Update metrics
                    if 'metrics' not in app.job_results[job_id]:
                        app.job_results[job_id]['metrics'] = {}
                    
                    # Store PublicWWW metrics in a separate section
                    if 'publicwww' not in app.job_results[job_id]['metrics']:
                        app.job_results[job_id]['metrics']['publicwww'] = {}
                    
                    app.job_results[job_id]['metrics']['publicwww'].update(metrics.copy() if metrics else {})
                    
                    # Update status based on metrics
                    status = metrics.get('status', '')
                    if status == 'complete':
                        # Don't change overall job status when this particular search completes
                        pass
                    elif status == 'error' or status.startswith('error') or status == 'failed':
                        # Only update status for errors
                        app.job_results[job_id]['status'] = 'running'  # Keep running even if this part fails
                    
                    # Generate appropriate message
                    message = "Processing PublicWWW..."
                    if status == 'publicwww_started':
                        message = f"Starting PublicWWW search for {vendor_name}..."
                    elif status == 'publicwww_searching':
                        message = f"Searching PublicWWW for {vendor_name}..."
                    elif status == 'publicwww_parsing_search':
                        message = f"Parsing PublicWWW search results..."
                    elif status == 'publicwww_analyzing':
                        message = f"Analyzing PublicWWW content..."
                    elif status == 'publicwww_grok_PREPARING':
                        message = f"Preparing PublicWWW data for analysis..."
                    elif status == 'publicwww_grok_API_CALL':
                        message = f"Sending PublicWWW data to Grok..."
                    elif status == 'publicwww_site_found' or status == 'publicwww_grok_FINALIZING':
                        message = f"Found {metrics.get('customers_found', 0)} potential customers on PublicWWW..."
                    elif status == 'complete':
                        message = f"PublicWWW search complete! Found {metrics.get('customers_found', 0)} customers."
                    elif status == 'error' or status.startswith('error') or status == 'failed':
                        message = f"PublicWWW error: {metrics.get('error_message', metrics.get('failure_reason', 'Unknown error'))}"
                    
                    # Calculate progress - PublicWWW search takes 40-60% of progress bar
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
                    if status == 'publicwww_started':
                        log_entry = {'type': 'info', 'message': f"Starting PublicWWW search for {vendor_name}..."}
                    elif status == 'publicwww_site_found' and metrics.get('sites_found', 0) > 0 and metrics.get('sites_found', 0) % 5 == 0:
                        # Log every 5 sites found
                        sites_found = metrics.get('sites_found', 0)
                        log_entry = {'type': 'success', 'message': f"PublicWWW: found {sites_found} websites so far"}
                    elif status == 'complete':
                        customers_found = metrics.get('customers_found', 0)
                        log_entry = {'type': 'success', 'message': f"PublicWWW search complete! Found {customers_found} customers."}
                    elif status == 'error' or status.startswith('error') or status == 'failed':
                        error_msg = metrics.get('error_message', metrics.get('failure_reason', 'Unknown error'))
                        log_entry = {'type': 'error', 'message': f"PublicWWW error: {error_msg}"}
                    
                    # Add timestamp and save the log entry if we created one
                    if log_entry:
                        log_entry['timestamp'] = time.time()
                        app.job_logs[job_id].append(log_entry)
                
                # Do the enhanced search with our callback
                enhanced_data = enhanced_vendor_search(vendor_name, max_results=max_results, status_callback=enhanced_search_callback)
                
                # Do the FeaturedCustomers search with our callback
                featured_data = scrape_featured_customers(vendor_name, max_results=max_results, status_callback=featured_customers_callback)
                
                # Do the Google search with our callback
                google_data = search_google(vendor_name, status_callback=google_search_callback)
                
                # Do the TrustRadius search with our callback
                trust_radius_data = scrape_trust_radius(vendor_name, max_results=max_results, status_callback=trust_radius_callback)
                
                # Do the PeerSpot search with our callback
                peerspot_data = scrape_peerspot(vendor_name, max_results=max_results, status_callback=peerspot_callback)
                
                # Do the BuiltWith search with our callback
                builtwith_data = scrape_builtwith(vendor_name, max_results=max_results, status_callback=builtwith_callback)
                
                # Do the PublicWWW search with our callback
                publicwww_data = scrape_publicwww(vendor_name, max_results=max_results, status_callback=publicwww_callback)
                
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
                app.job_logs[job_id].append(log_entry)
                
                # Combine results from all sources
                app_logger.info(f"Combining results from vendor site, " +
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
                
                # Track validation for logging
                original_urls = []
                validation_results = []
                
                # Get app logger
                format_logger = get_logger(LogComponent.APP)
                
                for item in combined_data:
                    # Get the URL from the item
                    url = item.get('url', None)
                    
                    if url:
                        original_urls.append(url)
                        
                        # First do basic structure validation (fast)
                        validation_result = validate_url(url, validate_dns=False, validate_http=False)
                        
                        # Only do DNS validation if structure is valid
                        if validation_result.structure_valid:
                            # Now validate DNS to check if domain actually resolves
                            dns_validation_result = validate_url(url, validate_dns=True, validate_http=False)
                            validation_results.append(dns_validation_result)
                            
                            # Only add to formatted results if DNS validation passes
                            if dns_validation_result.dns_valid:
                                formatted_results.append({
                                    'competitor': vendor_name,
                                    'customer_name': item.get('name', 'Unknown'),
                                    'customer_url': dns_validation_result.cleaned_url,
                                    'validation': {
                                        'structure_valid': dns_validation_result.structure_valid,
                                        'dns_valid': dns_validation_result.dns_valid,
                                        'http_valid': dns_validation_result.http_valid
                                    }
                                })
                            else:
                                # Log skipped URL due to DNS validation failure
                                format_logger.info(f"Skipping URL due to DNS validation failure: {dns_validation_result.cleaned_url} for {item.get('name', 'Unknown')}")
                        else:
                            # Structure invalid, keep the original validation result
                            validation_results.append(validation_result)
                            # Don't include structure-invalid URLs in results
                
                # Log validation statistics
                log_validation_stats(
                    original_urls, 
                    validation_results, 
                    context={'stage': 'app_final_formatting', 'vendor': vendor_name}
                )
                
                # Calculate validation stats for detailed logging
                structure_invalid_count = sum(1 for r in validation_results if not r.structure_valid)
                dns_invalid_count = sum(1 for r in validation_results if r.structure_valid and not r.dns_valid)
                valid_count = sum(1 for r in validation_results if r.dns_valid)
                
                # Log how many URLs were filtered out in this final step
                format_logger.info(f"URL validation summary: {valid_count} valid, {dns_invalid_count} DNS invalid, {structure_invalid_count} structure invalid")
                format_logger.info(f"Filtered out {structure_invalid_count + dns_invalid_count} URLs that didn't pass validation checks")
                
                # Log ALL URLs being sent to frontend regardless of validation status
                format_logger.info(f"ALL URLS being sent to frontend ({len(formatted_results)}):")
                for i, result in enumerate(formatted_results):
                    url = result.get('customer_url')
                    name = result.get('customer_name', 'Unknown')
                    validation_info = result.get('validation', {})
                    structure_valid = validation_info.get('structure_valid', False)
                    dns_valid = validation_info.get('dns_valid', False)
                    http_valid = validation_info.get('http_valid', False)
                    format_logger.info(f"  {i+1}. {name}: {url} [structure:{structure_valid}, dns:{dns_valid}, http:{http_valid}]")
                
                # Limit final results to the user-specified max_results if we have too many
                if len(formatted_results) > max_results:
                    app_logger.info(f"Limiting final results to requested amount")
                    formatted_results = formatted_results[:max_results]
                
                # Generate additional suggestions with Grok if we have fewer results than requested
                if len(formatted_results) < max_results:
                    app_logger.info(f"Generating additional suggestions to reach target count...")
                    additional_results = generate_additional_suggestions(vendor_name, formatted_results, max_results - len(formatted_results))
                    
                    # Add a source field to the original results for clarity
                    for result in formatted_results:
                        if "source" not in result:
                            result["source"] = "Scraped"
                    
                    # Add the additional results to our formatted results
                    formatted_results.extend(additional_results)
                    
                    app_logger.info(f"Added AI-generated suggestions to results")
                    
                    # Log entry for the AI generation
                    log_entry = {
                        'type': 'info',
                        'message': f"Generated additional potential customers with AI assistance",
                        'timestamp': time.time()
                    }
                    app.job_logs[job_id].append(log_entry)
                
                app_logger.info(f"Found customers for {vendor_name}")
                
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
                    'message': f"Search complete! Results found for {vendor_name}.",
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

# Function to generate additional customer suggestions using Grok AI
def generate_additional_suggestions(vendor_name, existing_results, count_needed):
    """
    Use Grok AI to generate additional customer suggestions when we have fewer results than requested.
    
    Args:
        vendor_name: The name of the vendor we're analyzing
        existing_results: The list of results we already have
        count_needed: How many additional results we need
        
    Returns:
        A list of additional suggested customers in the same format as existing_results
    """
    logger = get_logger(LogComponent.APP)
    logger.info(f"Generating {count_needed} additional customer suggestions for {vendor_name}")
    
    try:
        # Get Grok API key from environment
        api_key = os.environ.get('GROK_API_KEY')
        
        if not api_key:
            logger.error("GROK_API_KEY not found in environment variables")
            return []
        
        # Prepare a list of existing customer names to avoid duplicates
        existing_names = [result.get('customer_name', '').lower() for result in existing_results]
        
        # Format existing results for prompt context
        existing_context = ""
        for i, result in enumerate(existing_results[:10]):  # Limit to first 10 for context
            existing_context += f"{i+1}. {result.get('customer_name', 'Unknown')}\n"
        
        # Create a prompt for Grok to generate additional suggestions
        prompt = f"""
        I need to generate {count_needed} additional potential customers for {vendor_name}.
        
        Here are some customers we already know about:
        {existing_context}
        
        TASK: Generate {count_needed} additional companies that are likely to be customers of {vendor_name}. 
        These should be real companies in the same industry or with similar characteristics as the existing customers.
        
        IMPORTANT GUIDELINES:
        - Each company MUST be a real, existing company (not fictional)
        - DO NOT include any companies already in the list above
        - Focus on companies that would realistically use {vendor_name}'s products/services
        - Include both well-known companies and some less obvious choices
        - For each company, provide both the company name and their primary domain
        
        Please format your response as a JSON array with each company having "name" and "domain" fields:
        [
          {{"name": "Company Name 1", "domain": "company1.com"}},
          {{"name": "Company Name 2", "domain": "company2.com"}},
          ...
        ]
        
        Only respond with the JSON array, nothing else.
        """
        
        # Call X.AI API with proper authentication (using the Grok API key)
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'VendorCustomerIntelligenceTool/1.0',
            'X-Request-ID': f'additional-{vendor_name}-{int(time.time())}'
        }
        
        api_payload = {
            'model': 'grok-3-latest',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant that specializes in business intelligence and customer research.'},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 2000,
            'temperature': 0.7,  # Higher temperature for more varied suggestions
            'timeout': 50
        }
        
        # Make the API call
        logger.info(f"Calling Grok API to generate additional suggestions")
        response = requests.post(
            'https://api.x.ai/v1/chat/completions',
            headers=headers,
            timeout=60,
            json=api_payload
        )
        
        if response.status_code != 200:
            logger.error(f"Grok API error: {response.status_code} - {response.text}")
            return []
        
        # Process the response
        grok_response = response.json()
        generated_text = grok_response.get('choices', [{}])[0].get('message', {}).get('content', '')
        logger.info(f"Received valid response from Grok API: {len(generated_text)} characters")
        
        # Try to parse the JSON response
        try:
            # Find the JSON array in the response
            json_start = generated_text.find('[')
            json_end = generated_text.rfind(']') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = generated_text[json_start:json_end]
                suggestions = json.loads(json_str)
                
                # Format the suggestions as customer data
                additional_results = []
                for suggestion in suggestions:
                    # Skip if the company is already in our results
                    if suggestion.get('name', '').lower() in existing_names:
                        continue
                        
                    # Generate a proper URL
                    domain = suggestion.get('domain', '')
                    if not domain:
                        domain = f"{suggestion.get('name', '').lower().replace(' ', '')}.com"
                    
                    # Validate URL structure
                    validation_result = validate_url(domain, validate_dns=False, validate_http=False)
                    
                    # Only add if URL structure is valid
                    if validation_result.structure_valid:
                        # Add to results
                        additional_results.append({
                            'competitor': vendor_name,
                            'customer_name': suggestion.get('name', 'Unknown'),
                            'customer_url': validation_result.cleaned_url,
                            'source': 'AI Generated',
                            'validation': {
                                'structure_valid': validation_result.structure_valid,
                                'dns_valid': validation_result.dns_valid,
                                'http_valid': validation_result.http_valid
                            }
                        })
                        
                        # Add to existing names to avoid duplicates in future iterations
                        existing_names.append(suggestion.get('name', '').lower())
                    
                    # Stop if we have enough
                    if len(additional_results) >= count_needed:
                        break
                
                logger.info(f"Generated {len(additional_results)} additional suggestions")
                return additional_results
            else:
                logger.error("Could not find JSON array in Grok response")
                return []
        except Exception as e:
            logger.error(f"Error parsing Grok suggestions: {str(e)}")
            
            # Fallback to simple parsing if JSON parse fails
            suggestions = []
            lines = generated_text.strip().split('\n')
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                # Try to extract company name
                parts = line.split('-')
                if len(parts) >= 1:
                    name = parts[0].strip()
                    if len(name) < 2 or name.lower() in existing_names:
                        continue
                    
                    # Generate URL
                    url = f"{name.lower().replace(' ', '')}.com"
                    
                    # Validate URL structure
                    validation_result = validate_url(url, validate_dns=False, validate_http=False)
                    
                    # Only add if URL structure is valid
                    if validation_result.structure_valid:
                        suggestions.append({
                            'competitor': vendor_name,
                            'customer_name': name,
                            'customer_url': validation_result.cleaned_url,
                            'source': 'AI Generated',
                            'validation': {
                                'structure_valid': validation_result.structure_valid,
                                'dns_valid': validation_result.dns_valid,
                                'http_valid': validation_result.http_valid
                            }
                        })
                        
                        # Add to existing names to avoid duplicates
                        existing_names.append(name.lower())
                    
                    # Stop if we have enough
                    if len(suggestions) >= count_needed:
                        break
            
            logger.info(f"Generated {len(suggestions)} additional suggestions using fallback parsing")
            return suggestions
    
    except Exception as e:
        logger.error(f"Error generating additional suggestions: {str(e)}")
        return []

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
    
    # Get max_results parameter with a default of 20
    try:
        max_results = int(request.form.get('max_results', 20))
        # Ensure max_results is within reasonable limits
        max_results = max(1, min(100, max_results))
    except (ValueError, TypeError):
        max_results = 20
    
    # Set request context and get app logger
    set_context(vendor_name=vendor_name, request_path='/analyze', operation='analyze_vendor')
    app_logger = get_logger(LogComponent.APP)
    
    # Log the request
    app_logger.info(f"Received request to analyze vendor: {vendor_name} with max_results: {max_results}")
    
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
            'target_count': max_results
        },
        'vendor_name': vendor_name,
        'max_results': max_results,
        'start_time': time.time()
    }
    
    # Initialize logs for this job
    app.job_logs[job_id] = []
    
    # Add the job to the processing queue
    app.job_queue.put((job_id, vendor_name, max_results))
    app_logger.info(f"Added job {job_id} to processing queue with max_results: {max_results}")
    
    # Initial log entry
    log_entry = {
        'type': 'info',
        'message': f"Added {vendor_name} to processing queue with max_results: {max_results}...",
        'timestamp': time.time()
    }
    app.job_logs[job_id].append(log_entry)
    
    # Return the job ID immediately so the front end can start polling
    return render_template('results.html',
                          vendor_name=vendor_name,
                          job_id=job_id,
                          max_results=max_results,
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
