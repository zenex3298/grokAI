import os
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler

# Import configuration
from src.config import LOG_DIR, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT

def setup_logging():
    """Set up logging configuration."""
    # Create timestamped log directory for this run
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    run_log_dir = os.path.join(LOG_DIR, timestamp)
    os.makedirs(run_log_dir, exist_ok=True)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL))
    
    # Clear existing handlers
    for handler in root_logger.handlers[:]:  
        root_logger.removeHandler(handler)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, LOG_LEVEL))
    console_formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # Create file handlers for different components
    components = [
        'app',           # Main application logs
        'scraper',       # Web scraping logs
        'analyzer',      # Grok analyzer logs
        'api'            # API request logs
    ]
    
    for component in components:
        # Create component-specific log file
        log_file = os.path.join(run_log_dir, f"{component}.log")
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=10485760,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(getattr(logging, LOG_LEVEL))
        
        # Create formatter
        file_formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
        file_handler.setFormatter(file_formatter)
        
        # Create component logger
        component_logger = logging.getLogger(component)
        component_logger.setLevel(getattr(logging, LOG_LEVEL))
        component_logger.addHandler(file_handler)
        component_logger.propagate = True  # Also send to root logger
    
    # Return the main application logger
    return logging.getLogger('app')

def get_component_logger(component_name):
    """Get a logger for a specific component."""
    return logging.getLogger(component_name)
