import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Configuration
GROK_API_KEY = os.environ.get('GROK_API_KEY')

# Logging Configuration
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Application Settings
DEBUG = os.environ.get('FLASK_DEBUG', 'False') == 'True'

# Log directory
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
