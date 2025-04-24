import os
import time
import threading
import queue
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from src.scrapers.vendor_site import scrape_vendor_site
from src.scrapers.enhanced_search import enhanced_vendor_search
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
                    'step': 50,
                    'message': f'Running enhanced search with Grok for {vendor_name}...'
                }
                
                # Log entry for enhanced search
                log_entry = {'type': 'info', 'message': f"Running enhanced search with Grok for {vendor_name}...", 'timestamp': time.time()}
                app.job_logs[job_id].append(log_entry)
                
                # Step 2: Do enhanced search with status callback
                def update_status(metrics):
                    # Update metrics
                    if 'metrics' not in app.job_results[job_id]:
                        app.job_results[job_id]['metrics'] = {}
                    app.job_results[job_id]['metrics'].update(metrics.copy() if metrics else {})
                    
                    # Update status based on metrics
                    status = metrics.get('status', '')
                    app.job_results[job_id]['status'] = status if status != 'complete' else 'completed'
                    
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
                        message = f"Analysis complete! Found {metrics.get('companies_found', 0)} companies."
                    elif status == 'error' or status.startswith('error'):
                        message = f"Error: {metrics.get('error_message', 'Unknown error occurred')}"
                    
                    # Update progress
                    progress_step = 50
                    if status == 'complete':
                        progress_step = 80
                    elif status.startswith('error'):
                        progress_step = 80
                    elif 'companies_found' in metrics and 'target_count' in metrics and metrics['target_count'] > 0:
                        companies_ratio = min(1.0, metrics['companies_found'] / metrics['target_count'])
                        progress_step = 50 + int(companies_ratio * 30)
                    
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
                        log_entry = {'type': 'success', 'message': f"Found {companies_found} companies so far"}
                    elif status == 'complete':
                        companies_found = metrics.get('companies_found', 0)
                        unique_companies = metrics.get('unique_companies_count', 0) or metrics.get('unique_companies', 0)
                        log_entry = {'type': 'success', 'message': f"Analysis complete! Found {companies_found} companies, {unique_companies} unique."}
                    elif status.startswith('error') or status == 'failed':
                        error_msg = metrics.get('error_message', 'Unknown error')
                        log_entry = {'type': 'error', 'message': f"Error: {error_msg}"}
                    
                    # Add timestamp and save the log entry if we created one
                    if log_entry:
                        log_entry['timestamp'] = time.time()
                        app.job_logs[job_id].append(log_entry)
                
                # Do the enhanced search with our callback
                enhanced_data = enhanced_vendor_search(vendor_name, max_results=5, status_callback=update_status)
                
                # Extract results and metrics
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
                    'message': 'Combining results...'
                }
                
                # Combine results, preferring enhanced data
                combined_data = vendor_data.copy()
                
                # Add enhanced data, avoiding duplicates
                existing_names = {item.get('name', '').lower() for item in vendor_data}
                for item in results_data:
                    if item.get('name', '').lower() not in existing_names:
                        combined_data.append(item)
                
                # Format the data for the results template
                formatted_results = []
                # Limit to maximum 5 results
                max_to_display = 5
                
                for i, item in enumerate(combined_data):
                    # Get the URL from the item
                    url = item.get('url', None)
                    
                    # Skip items without a valid URL
                    if not url:
                        continue
                        
                    # Only include the first max_to_display items
                    if len(formatted_results) >= max_to_display:
                        break
                        
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
            'target_count': 5
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
