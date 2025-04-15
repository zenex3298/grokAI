# Vendor Customer Intelligence Tool

A web-based tool for extracting and analyzing client/customer information from vendor websites and supplementary sources using Grok AI.

## Features

- **Vendor Website Scraping**: Extracts customer information from vendor websites, including logo sections and case studies
- **Multi-Source Data Collection**: Gathers data from various sources like FeaturedCustomers, Google searches, and technology-specific platforms
- **AI-Powered Analysis**: Uses Grok AI to process and summarize findings into a clean, structured format
- **Simple User Interface**: Easy-to-use form for inputting vendor names and viewing results

## Getting Started

### Prerequisites

- Python 3.8+
- Grok AI API key

### Installation

1. Clone the repository
```bash
git clone https://github.com/yourusername/vendor-intelligence-tool.git
cd vendor-intelligence-tool
```

2. Install dependencies
```bash
pip install -r requirements.txt
```

3. Set up environment variables
```bash
# Create a .env file
echo "GROK_API_KEY=your_api_key_here" > .env
echo "PORT=5000" >> .env
```

### Running Locally

```bash
python app.py
```

The application will be available at `http://localhost:5000`

## Deployment on Heroku

1. Create a Heroku account and install the Heroku CLI

2. Login to Heroku CLI
```bash
heroku login
```

3. Create a new Heroku app
```bash
heroku create vendor-intelligence-tool
```

4. Set up environment variables on Heroku
```bash
heroku config:set GROK_API_KEY=your_api_key_here
```

5. Push to Heroku
```bash
git push heroku main
```

## Project Structure

```
vendor-intelligence-tool/
├── app.py                 # Main application file
├── Procfile               # Heroku deployment configuration
├── requirements.txt       # Project dependencies
├── runtime.txt            # Python runtime specification
├── .env                   # Environment variables (local development)
├── .gitignore             # Git ignore file
├── logs/                  # Log directory
├── static/                # Static files (CSS, JS, images)
│   ├── css/
│   │   └── styles.css
│   └── js/
│       └── main.js
├── templates/             # HTML templates
│   ├── index.html
│   └── results.html
└── src/
    ├── __init__.py
    ├── config.py          # Configuration settings
    ├── scrapers/          # Website scraping modules
    │   ├── __init__.py
    │   ├── vendor_site.py
    │   ├── featured_customers.py
    │   └── search_engines.py
    ├── analyzers/         # Data analysis modules
    │   ├── __init__.py
    │   └── grok_analyzer.py
    └── utils/             # Utility functions
        ├── __init__.py
        └── logger.py
```

## Architecture

The application follows a modular architecture:

1. **User Input**: Front-end form collects vendor name
2. **Data Collection**: Multiple scrapers gather information from various sources
3. **AI Analysis**: Collected data is processed by Grok AI
4. **Results Presentation**: Findings are formatted into an HTML table and presented to the user

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.