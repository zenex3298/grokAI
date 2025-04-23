import os
import threading
import queue
import time
import json
from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
from src.scrapers.vendor_site import scrape_vendor_site
from src.scrapers.featured_customers import scrape_featured_customers
from src.scrapers.search_engines import search_google
from src.analyzers.grok_analyzer import analyze_with_grok
from src.utils.logger import setup_logging, get_logger, LogComponent, set_context
from src.utils.data_validator import (
    validate_customer_data, 
    validate_combined_data,
    ValidationLevel,
    is_empty_data
)

# Global job queue and results store
job_queue = queue.Queue()
job_results = {}

# Progress tracking for each step of the analysis
PROGRESS_STEPS = {
    'INIT': {'step': 0, 'message': 'Initializing analysis...'},
    'SCRAPING': {'step': 10, 'message': 'Scraping vendor site...'},
    'SEARCH': {'step': 30, 'message': 'Searching for customer information...'},
    'PREPARING': {'step': 50, 'message': 'Preparing data for analysis...'},
    'API_CALL': {'step': 60, 'message': 'Analyzing with AI...'},
    'FINALIZING': {'step': 90, 'message': 'Finalizing results...'},
    'COMPLETE': {'step': 100, 'message': 'Analysis complete!'},
    'ERROR': {'step': 100, 'message': 'Error occurred during analysis'}
}

# Load environment variables
load_dotenv()

# Configure logging
logger = setup_logging()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev_secret_key')

# Worker thread function to process jobs in the background
def worker():
    """Background worker that processes API calls asynchronously."""
    # Get worker-specific logger
    worker_logger = get_logger(LogComponent.WORKER)
    worker_logger.info("Starting background worker thread")
    
    while True:
        try:
            # Get a job from the queue
            job_id, vendor_name, validated_data = job_queue.get(timeout=1)
            
            # Set context for this job
            set_context(vendor_name=vendor_name, job_id=job_id, operation="grok_analysis")
            worker_logger.info(f"Worker processing job {job_id} for vendor {vendor_name}")
            
            # Update job status to running if it exists, otherwise initialize it
            if job_id in job_results:
                job_results[job_id].update({
                    'status': 'running',
                    'progress': PROGRESS_STEPS['API_CALL']
                })
            else:
                # Should never happen if job was properly initialized in /analyze
                job_results[job_id] = {
                    'status': 'running',
                    'progress': PROGRESS_STEPS['API_CALL'],
                    'partial_results': [],
                    'results': [],
                    'error': None,
                    'vendor_name': vendor_name,
                    'start_time': time.time()
                }
            
            # Final validation check before sending to API
            # This is a safeguard in case the job was queued without validation
            if is_empty_data(validated_data, min_items=3):
                error_message = "Insufficient data for analysis. No valid customer data found."
                worker_logger.warning(f"Data validation failed in worker for job {job_id}: {error_message}")
                
                job_results[job_id].update({
                    'status': 'failed',
                    'progress': PROGRESS_STEPS['ERROR'],
                    'results': [],
                    'error': error_message,
                    'error_details': {
                        'type': 'worker_validation_error',
                        'count': len(validated_data)
                    },
                    'end_time': time.time(),
                    'duration': time.time() - job_results[job_id]['start_time']
                })
                job_queue.task_done()
                continue
            
            # Process with Grok AI
            try:
                worker_logger.info(f"Starting Grok analysis for job {job_id} with {len(validated_data)} validated items")
                
                # Register a progress callback
                def update_progress(stage, partial_results=None, message=None):
                    worker_logger.debug(f"Progress update: {stage}, {message}")
                    
                    if stage in PROGRESS_STEPS:
                        job_results[job_id]['progress'] = PROGRESS_STEPS[stage]
                    else:
                        # Custom progress stage (percentage-based)
                        try:
                            # Try to convert stage to float/int if it's a number
                            stage_num = float(stage)
                            job_results[job_id]['progress'] = {
                                'step': 60 + (stage_num * 30 / 100),  # Map 0-100 to 60-90 range
                                'message': message or f'Processing... {stage_num:.0f}%'
                            }
                        except (ValueError, TypeError):
                            # If not a number, use as-is
                            job_results[job_id]['progress'] = {
                                'step': 75,  # Default to 75% if we can't determine stage
                                'message': message or f'Processing... {stage}'
                            }
                    
                    # If we have partial results, add them
                    if partial_results:
                        # Validate partial results
                        if isinstance(partial_results, list):
                            # Basic validation of partial results format
                            valid_partial = [item for item in partial_results 
                                            if isinstance(item, dict) and 'customer_name' in item]
                            
                            if valid_partial:
                                job_results[job_id]['partial_results'] = valid_partial
                                worker_logger.debug(f"Updated partial results: {len(valid_partial)} items")
                
                # Call analysis with progress tracking
                results = analyze_with_grok(validated_data, vendor_name, progress_callback=update_progress)
                
                # Validate final results
                if not results or len(results) == 0:
                    worker_logger.warning(f"Grok analysis returned no results for job {job_id}")
                    
                    # If we have partial results, use those instead
                    if job_results[job_id].get('partial_results'):
                        worker_logger.info(f"Using {len(job_results[job_id]['partial_results'])} partial results as final results")
                        results = job_results[job_id]['partial_results']
                
                # Update with final results
                job_results[job_id].update({
                    'status': 'completed',
                    'progress': PROGRESS_STEPS['COMPLETE'],
                    'results': results,
                    'end_time': time.time(),
                    'duration': time.time() - job_results[job_id]['start_time']
                })
                worker_logger.info(f"Job {job_id} completed successfully with {len(results)} results")
                
            except Exception as e:
                worker_logger.exception(f"Error in worker thread processing job {job_id}: {str(e)}")
                
                # Check if we have partial results we can use
                partial_results = job_results[job_id].get('partial_results', [])
                if partial_results and len(partial_results) > 0:
                    worker_logger.info(f"Using {len(partial_results)} partial results despite error")
                    
                    # Complete the job with partial results
                    job_results[job_id].update({
                        'status': 'completed_with_errors',
                        'progress': PROGRESS_STEPS['COMPLETE'],
                        'results': partial_results,
                        'error': str(e),
                        'error_details': {
                            'type': 'recoverable_error',
                            'partial_results_used': True
                        },
                        'end_time': time.time(),
                        'duration': time.time() - job_results[job_id]['start_time']
                    })
                else:
                    # No partial results available, mark as failed
                    job_results[job_id].update({
                        'status': 'failed',
                        'progress': PROGRESS_STEPS['ERROR'],
                        'results': [],
                        'error': str(e),
                        'error_details': {
                            'type': 'processing_error'
                        },
                        'end_time': time.time(),
                        'duration': time.time() - job_results[job_id]['start_time']
                    })
            finally:
                job_queue.task_done()
                
        except queue.Empty:
            # Queue is empty, just continue and check again
            pass
        except Exception as e:
            worker_logger.exception(f"Unexpected error in worker thread: {str(e)}")
            # Don't crash the worker thread
            time.sleep(1)  # Avoid tight loop in case of repeated errors

# Start the worker thread
worker_thread = threading.Thread(target=worker, daemon=True)
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
    
    try:
        # Create a job ID early for tracking
        job_id = f"{vendor_name}_{int(time.time())}"
        app_logger.info(f"Created job ID: {job_id}")
        
        # Store job ID in session for the user
        session['job_id'] = job_id
        
        # Initialize job status for immediate feedback
        job_results[job_id] = {
            'status': 'initializing',
            'progress': PROGRESS_STEPS['INIT'],
            'partial_results': [],
            'results': [],
            'error': None,
            'vendor_name': vendor_name,
            'start_time': time.time(),
            'validation_status': {
                'vendor_site': {'status': 'pending'},
                'featured_customers': {'status': 'pending'},
                'search_engines': {'status': 'pending'},
                'combined': {'status': 'pending'}
            }
        }
        
        # Step 1: Scrape vendor website with validation
        app_logger.info(f"Scraping vendor site for {vendor_name}")
        job_results[job_id]['progress'] = PROGRESS_STEPS['SCRAPING']
        vendor_data = scrape_vendor_site(vendor_name)
        
        # Validate vendor data (minimum 1 item with MEDIUM validation)
        vendor_validation = validate_customer_data(
            vendor_data, 
            vendor_name, 
            min_items=1,
            level=ValidationLevel.MEDIUM,
            context={'source': 'vendor_site', 'job_id': job_id}
        )
        
        # Store validation results for client feedback
        job_results[job_id]['validation_status']['vendor_site'] = {
            'status': 'valid' if vendor_validation.is_valid else 'invalid',
            'count': len(vendor_validation.filtered_data),
            'original_count': len(vendor_data),
            'reasons': vendor_validation.reasons
        }
        
        # Step 2: Get data from Featured Customers with validation
        app_logger.info(f"Scraping Featured Customers for {vendor_name}")
        featured_data = scrape_featured_customers(vendor_name)
        
        # Validate featured data (minimum 0 items, just for filtering)
        featured_validation = validate_customer_data(
            featured_data, 
            vendor_name, 
            min_items=0,
            level=ValidationLevel.HIGH,
            context={'source': 'featured_customers', 'job_id': job_id}
        )
        
        # Store validation results
        job_results[job_id]['validation_status']['featured_customers'] = {
            'status': 'valid' if featured_validation.is_valid else 'invalid',
            'count': len(featured_validation.filtered_data),
            'original_count': len(featured_data),
            'reasons': featured_validation.reasons
        }
        
        # Step 3: Search Google with validation
        app_logger.info(f"Searching Google for {vendor_name}")
        job_results[job_id]['progress'] = PROGRESS_STEPS['SEARCH']
        google_data = search_google(vendor_name)
        
        # Validate search data (minimum 0 items, just for filtering)
        search_validation = validate_customer_data(
            google_data, 
            vendor_name, 
            min_items=0,
            level=ValidationLevel.LOW,  # Lower standards for search results
            context={'source': 'search_engines', 'job_id': job_id}
        )
        
        # Store validation results
        job_results[job_id]['validation_status']['search_engines'] = {
            'status': 'valid' if search_validation.is_valid else 'invalid',
            'count': len(search_validation.filtered_data),
            'original_count': len(google_data),
            'reasons': search_validation.reasons
        }
        
        # Step 4: Validate combined data
        job_results[job_id]['progress'] = PROGRESS_STEPS['PREPARING']
        app_logger.info(f"Validating combined data for {vendor_name}")
        
        # Use filtered data from each source for combined validation
        combined_validation = validate_combined_data(
            vendor_validation.filtered_data,
            featured_validation.filtered_data,
            search_validation.filtered_data,
            vendor_name,
            min_total=3,  # Require at least 3 valid items across all sources
            level=ValidationLevel.MEDIUM
        )
        
        # Store combined validation results
        job_results[job_id]['validation_status']['combined'] = {
            'status': 'valid' if combined_validation.is_valid else 'invalid',
            'count': len(combined_validation.filtered_data),
            'original_count': len(vendor_data) + len(featured_data) + len(google_data),
            'reasons': combined_validation.reasons
        }
        
        # Check if combined data passes validation
        if not combined_validation.is_valid:
            # Not enough valid data found - set error in job results
            error_message = "Insufficient valid customer data found. Please try a different vendor name."
            app_logger.warning(f"Validation failed for {vendor_name}: {error_message}",
                             extra={'reasons': combined_validation.reasons})
            
            job_results[job_id].update({
                'status': 'failed',
                'progress': PROGRESS_STEPS['ERROR'],
                'error': error_message,
                'error_details': {
                    'type': 'validation_error',
                    'reasons': combined_validation.reasons,
                    'metrics': combined_validation.metrics
                }
            })
            
            # Return results page that will show the error
            return render_template('results.html', 
                                   vendor_name=vendor_name,
                                   job_id=job_id,
                                   results=None,
                                   polling=True)
        
        # Use filtered data for processing
        filtered_data = combined_validation.filtered_data
        
        # Log the filtered combined data
        app_logger.info(f"Validated combined data for {vendor_name}: {len(filtered_data)} items (from {len(vendor_data) + len(featured_data) + len(google_data)} original)")
        for item in filtered_data:
            app_logger.info(f"Validated data item - Name: {item.get('name', 'N/A')}, URL: {item.get('url', 'N/A')}, Source: {item.get('source', 'unknown')}")
        
        # Update job status
        job_results[job_id]['partial_results'] = filtered_data
        
        # Add job to queue for background processing with validated data
        job_queue.put((job_id, vendor_name, filtered_data))
        app_logger.info(f"Job {job_id} added to queue with {len(filtered_data)} validated items, redirecting to results page")
        
        # Immediately return a results page that will check for job completion
        return render_template('results.html', 
                               vendor_name=vendor_name,
                               job_id=job_id,
                               results=None,  # No results yet
                               polling=True)  # Indicate that we need to poll for results
    
    except Exception as e:
        app_logger.exception(f"Error analyzing vendor {vendor_name}: {str(e)}")
        
        # Initialize job result if it doesn't exist yet
        if job_id not in job_results:
            job_results[job_id] = {
                'status': 'failed',
                'progress': PROGRESS_STEPS['ERROR'],
                'partial_results': [],
                'results': [],
                'error': str(e),
                'vendor_name': vendor_name,
                'start_time': time.time()
            }
        else:
            # Update existing job with error
            job_results[job_id].update({
                'status': 'failed',
                'progress': PROGRESS_STEPS['ERROR'],
                'error': str(e)
            })
            
        return jsonify({'error': str(e)}), 500

@app.route('/job_status/<job_id>', methods=['GET'])
def job_status(job_id):
    """Check the status of a background job."""
    if job_id in job_results:
        job = job_results[job_id]
        
        # Common fields to include in all responses
        response = {
            'status': job['status'],
            'progress': job['progress'],
            'vendor_name': job['vendor_name'],
            'job_id': job_id,
            'elapsed_time': time.time() - job['start_time']
        }
        
        # Include validation status if it exists
        if 'validation_status' in job:
            response['validation_status'] = job['validation_status']
        
        # Status-specific fields
        if job['status'] == 'completed':
            # Job is done, return the results
            response.update({
                'results': job['results'],
                'duration': job.get('duration', 0),
                'partial_results': []  # Clear partial results once complete
            })
        elif job['status'] == 'failed':
            # Job failed, return the error
            response.update({
                'error': job['error'],
                'error_details': job.get('error_details', {}),
                'partial_results': job.get('partial_results', [])
            })
        else:
            # Job is initializing or running
            response.update({
                'partial_results': job.get('partial_results', [])
            })
        
        return jsonify(response)
    
    # Job doesn't exist
    return jsonify({
        'status': 'pending',
        'progress': {'step': 0, 'message': 'Waiting to start...'}
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'False') == 'True')
