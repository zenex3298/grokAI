import os
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from src.scrapers.vendor_site import scrape_vendor_site
from src.scrapers.featured_customers import scrape_featured_customers
from src.scrapers.search_engines import search_google
from src.analyzers.grok_analyzer import analyze_with_grok
from src.utils.logger import setup_logging

# Load environment variables
load_dotenv()

# Configure logging
logger = setup_logging()

# Initialize Flask app
app = Flask(__name__)

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
        
        # Step 5: Analyze with Grok AI
        logger.info(f"Analyzing data with Grok AI for {vendor_name}")
        analysis_result = analyze_with_grok(combined_data, vendor_name)
        
        # Return the results
        return render_template('results.html', 
                               vendor_name=vendor_name, 
                               results=analysis_result)
    
    except Exception as e:
        logger.error(f"Error analyzing vendor {vendor_name}: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'False') == 'True')
