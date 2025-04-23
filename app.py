import os
import threading
import queue
import time
from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
from src.scrapers.vendor_site import scrape_vendor_site
from src.scrapers.featured_customers import scrape_featured_customers
from src.scrapers.search_engines import search_google
from src.analyzers.grok_analyzer import analyze_with_grok
from src.utils.logger import setup_logging

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
    logger.info("Starting background worker thread")
    while True:
        try:
            # Get a job from the queue
            job_id, vendor_name, combined_data = job_queue.get(timeout=1)
            logger.info(f"Worker processing job {job_id} for vendor {vendor_name}")
            
            # Initialize job status with progress tracking
            job_results[job_id] = {
                'status': 'running',
                'progress': PROGRESS_STEPS['INIT'],
                'partial_results': [],
                'results': [],
                'error': None,
                'vendor_name': vendor_name,
                'start_time': time.time()
            }
            
            # Process with Grok AI
            try:
                # Update progress to API call stage
                job_results[job_id]['progress'] = PROGRESS_STEPS['API_CALL']
                
                # Register a progress callback
                def update_progress(stage, partial_results=None, message=None):
                    if stage in PROGRESS_STEPS:
                        job_results[job_id]['progress'] = PROGRESS_STEPS[stage]
                    else:
                        # Custom progress stage
                        job_results[job_id]['progress'] = {
                            'step': 60 + (stage * 30 / 100),  # Map 0-100 to 60-90 range
                            'message': message or f'Processing... {stage}%'
                        }
                    
                    # If we have partial results, add them
                    if partial_results:
                        job_results[job_id]['partial_results'] = partial_results
                
                # Call analysis with progress tracking
                results = analyze_with_grok(combined_data, vendor_name, progress_callback=update_progress)
                
                # Update with final results
                job_results[job_id].update({
                    'status': 'completed',
                    'progress': PROGRESS_STEPS['COMPLETE'],
                    'results': results,
                    'end_time': time.time(),
                    'duration': time.time() - job_results[job_id]['start_time']
                })
                logger.info(f"Job {job_id} completed successfully with {len(results)} results")
                
            except Exception as e:
                logger.error(f"Error in worker thread processing job {job_id}: {str(e)}")
                job_results[job_id].update({
                    'status': 'failed',
                    'progress': PROGRESS_STEPS['ERROR'],
                    'results': [],
                    'error': str(e),
                    'end_time': time.time(),
                    'duration': time.time() - job_results[job_id]['start_time']
                })
            finally:
                job_queue.task_done()
                
        except queue.Empty:
            # Queue is empty, just continue and check again
            pass
        except Exception as e:
            logger.error(f"Unexpected error in worker thread: {str(e)}")
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
    
    # Log the request
    logger.info(f"Received request to analyze vendor: {vendor_name}")
    
    try:
        # Step 1: Scrape vendor website
        logger.info(f"Scraping vendor site for {vendor_name}")
        vendor_data = scrape_vendor_site(vendor_name)
        
        # Step 2: Get data from Featured Customers
        logger.info(f"Scraping Featured Customers for {vendor_name}")
        featured_data = scrape_featured_customers(vendor_name)
        
        # Step 3: Search Google
        logger.info(f"Searching Google for {vendor_name}")
        google_data = search_google(vendor_name)
        
        # Step 4: Combine all data
        combined_data = vendor_data + featured_data + google_data
        
        # Log the combined data
        logger.info(f"Combined data for {vendor_name}: {len(combined_data)} items")
        for item in combined_data:
            logger.info(f"Data item - Name: {item.get('name', 'N/A')}, URL: {item.get('url', 'N/A')}, Source: {item.get('source', 'unknown')}")
        
        # Step 5: Create a job ID and add the job to the background queue
        job_id = f"{vendor_name}_{int(time.time())}"
        logger.info(f"Creating job {job_id} for asynchronous processing")
        
        # Store job ID in session for the user
        session['job_id'] = job_id
        
        # Add job to queue for background processing
        job_queue.put((job_id, vendor_name, combined_data))
        logger.info(f"Job {job_id} added to queue, redirecting to results page")
        
        # Immediately return a results page that will check for job completion
        return render_template('results.html', 
                               vendor_name=vendor_name,
                               job_id=job_id,
                               results=None,  # No results yet
                               polling=True)  # Indicate that we need to poll for results
    
    except Exception as e:
        logger.error(f"Error analyzing vendor {vendor_name}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/job_status/<job_id>', methods=['GET'])
def job_status(job_id):
    """Check the status of a background job."""
    if job_id in job_results:
        job = job_results[job_id]
        
        if job['status'] == 'completed':
            # Job is done, return the results
            return jsonify({
                'status': 'completed',
                'results': job['results'],
                'progress': job['progress'],
                'duration': job.get('duration', 0)
            })
        elif job['status'] == 'failed':
            # Job failed, return the error
            return jsonify({
                'status': 'failed',
                'error': job['error'],
                'progress': job['progress']
            })
        else:
            # Job is still running, return progress and partial results
            return jsonify({
                'status': 'running',
                'progress': job['progress'],
                'partial_results': job['partial_results'],
                'elapsed_time': time.time() - job['start_time']
            })
    
    # Job doesn't exist
    return jsonify({
        'status': 'pending',
        'progress': {'step': 0, 'message': 'Waiting to start...'}
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'False') == 'True')
