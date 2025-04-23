import os
import sys
import json
import uuid
import socket
import inspect
import logging
import functools
import threading
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler

# Import configuration
from src.config import (
    LOG_DIR,
    LOG_LEVEL,
    LOG_FORMAT,
    LOG_DATE_FORMAT,
)

# Define log component namespaces
class LogComponent:
    """Enum-like class for log component names"""
    APP = 'app'              # Main application logs
    SCRAPER = 'scraper'      # Scraper component logs
    VENDOR_SITE = 'vendor_site'  # Vendor site scraper logs
    FEATURED = 'featured'    # Featured customers scraper logs
    SEARCH = 'search'        # Search engine scraper logs
    ANALYZER = 'analyzer'    # Analysis component logs
    GROK = 'grok'            # Grok API integration logs
    API = 'api'              # External API communication logs
    DATA = 'data'            # Data processing and validation logs
    WEB = 'web'              # Web server and request handling logs
    WORKER = 'worker'        # Background worker process logs
    SYSTEM = 'system'        # System-level events logs

# Dictionary to store loggers
_loggers = {}

# Thread-local storage for context information
_context = threading.local()

def set_context(**kwargs):
    """Set context information for the current thread.
    
    This function can be used to add contextual information such as:
    - request_id: A unique identifier for the current request
    - vendor_name: The name of the vendor being processed
    - job_id: The ID of the current job
    - user_id: The ID of the current user
    """
    if not hasattr(_context, 'data'):
        _context.data = {}
    
    for key, value in kwargs.items():
        _context.data[key] = value

def get_context():
    """Get the current thread's context as a dictionary."""
    if not hasattr(_context, 'data'):
        _context.data = {}
    
    # Generate a request_id if one doesn't exist
    if 'request_id' not in _context.data:
        _context.data['request_id'] = str(uuid.uuid4())
        
    return _context.data

def _clear_context():
    """Clear the context for the current thread."""
    if hasattr(_context, 'data'):
        _context.data = {}

class ContextFilter(logging.Filter):
    """Filter that adds context information to log records."""
    
    def filter(self, record):
        # Add context information to the record
        context = get_context()
        for key, value in context.items():
            setattr(record, key, value)
        
        # Add call information
        if not hasattr(record, 'function'):
            record.function = record.funcName
        
        # Add hostname
        if not hasattr(record, 'hostname'):
            record.hostname = socket.gethostname()
        
        return True

class StructuredFormatter(logging.Formatter):
    """A formatter that outputs logs in a structured format."""
    
    def format(self, record):
        """Format the record as a structured log entry."""
        # Start with the basic formatted message
        basic_formatted = super().format(record)
        
        # Add record attributes we want to include
        data = {
            'timestamp': self.formatTime(record, self.datefmt),
            'level': record.levelname,
            'component': record.name,
            'message': record.getMessage(),
            'hostname': getattr(record, 'hostname', socket.gethostname()),
        }
        
        # Include location information
        if hasattr(record, 'pathname'):
            data['location'] = {
                'file': record.pathname,
                'line': record.lineno,
                'function': record.funcName,
            }
        
        # Include exception information
        if record.exc_info:
            data['exception'] = {
                'type': str(record.exc_info[0].__name__),
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }
        
        # Include all context fields
        context = get_context()
        if context:
            data['context'] = context
            
        # Include any extra attributes
        for key, value in record.__dict__.items():
            if key not in ('args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
                          'funcName', 'id', 'levelname', 'levelno', 'lineno', 'module',
                          'msecs', 'message', 'msg', 'name', 'pathname', 'process',
                          'processName', 'relativeCreated', 'stack_info', 'thread', 'threadName',
                          'hostname', 'context'):
                data[key] = value
                
        # Return formatted text log for console/file
        return basic_formatted

class DataMetricsFilter(logging.Filter):
    """Filter that calculates metrics for data processing logs."""
    
    def filter(self, record):
        # Process data metrics for relevant log messages
        if hasattr(record, 'data_metrics'):
            metrics = record.data_metrics
            
            # Add additional metrics calculations
            if 'items_count' in metrics and 'items_processed' in metrics:
                metrics['success_rate'] = metrics['items_processed'] / metrics['items_count'] if metrics['items_count'] > 0 else 0
                
            if 'start_time' in metrics and 'end_time' in metrics:
                metrics['processing_time'] = metrics['end_time'] - metrics['start_time']
                
            record.data_metrics = metrics
            
        return True

# Set up global exception handler to ensure errors are logged
def global_exception_handler(exc_type, exc_value, exc_traceback):
    """Custom exception handler to ensure errors are logged before the program exits."""
    if issubclass(exc_type, KeyboardInterrupt):
        # Call the default handler for KeyboardInterrupt
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
        
    # Get a system logger
    logger = get_logger(LogComponent.SYSTEM)
    logger.critical("Uncaught exception", 
                   exc_info=(exc_type, exc_value, exc_traceback), 
                   extra={'uncaught': True})
    
    # Write to a special crash log file
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        crash_file = os.path.join(LOG_DIR, f"crash_{timestamp}.log")
        with open(crash_file, 'w') as f:
            f.write(f"FATAL ERROR at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("".join(traceback.format_exception(exc_type, exc_value, exc_traceback)))
            
            # Add context information if available
            context = get_context()
            if context:
                f.write("\nContext Information:\n")
                f.write(json.dumps(context, indent=2))
    except:
        pass  # If we can't write to the crash file, don't make things worse
    
    # Call the default handler
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

def get_structured_formatter():
    """Get a formatter for structured logging."""
    return StructuredFormatter(
        fmt=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT
    )

def get_component_handler(component, run_log_dir):
    """Get a file handler for a specific component."""
    log_file = os.path.join(run_log_dir, f"{component}.log")
    
    file_handler = RotatingFileHandler(
        log_file, 
        maxBytes=10485760,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(getattr(logging, LOG_LEVEL))
    file_handler.setFormatter(get_structured_formatter())
    
    # Add a filter to only include logs for this component
    class ComponentFilter(logging.Filter):
        def filter(self, record):
            return record.name.startswith(component)
    
    file_handler.addFilter(ComponentFilter())
    
    return file_handler

def setup_logging():
    """Set up logging configuration."""
    # Create timestamped log directory for this run
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    run_log_dir = os.path.join(LOG_DIR, timestamp)
    os.makedirs(run_log_dir, exist_ok=True)
    
    # Register the global exception handler
    sys.excepthook = global_exception_handler
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL))
    
    # Clear existing handlers
    for handler in root_logger.handlers[:]:  
        root_logger.removeHandler(handler)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, LOG_LEVEL))
    console_formatter = get_structured_formatter()
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # Create a main log file that captures everything
    main_log_file = os.path.join(run_log_dir, "all.log")
    file_handler = RotatingFileHandler(
        main_log_file, 
        maxBytes=10485760,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(getattr(logging, LOG_LEVEL))
    file_formatter = get_structured_formatter()
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)
    
    # Add context filter to root logger
    context_filter = ContextFilter()
    root_logger.addFilter(context_filter)
    
    # Add data metrics filter to root logger
    metrics_filter = DataMetricsFilter()
    root_logger.addFilter(metrics_filter)
    
    # Create file handlers for different components
    components = [
        LogComponent.APP,
        LogComponent.SCRAPER,
        LogComponent.ANALYZER,
        LogComponent.API,
        LogComponent.DATA,
        LogComponent.WEB,
        LogComponent.WORKER,
        LogComponent.SYSTEM
    ]
    
    for component in components:
        # Create component-specific log file and handler
        component_handler = get_component_handler(component, run_log_dir)
        
        # Create component logger
        component_logger = logging.getLogger(component)
        component_logger.setLevel(getattr(logging, LOG_LEVEL))
        component_logger.addHandler(component_handler)
        component_logger.propagate = True  # Also send to root logger
        
        # Store in our logger cache
        _loggers[component] = component_logger
    
    # Register special sub-component loggers
    scraper_components = [
        LogComponent.VENDOR_SITE, 
        LogComponent.FEATURED, 
        LogComponent.SEARCH
    ]
    
    for component in scraper_components:
        # Create a logger that inherits from the scraper logger
        sublogger = logging.getLogger(f"{LogComponent.SCRAPER}.{component}")
        sublogger.setLevel(getattr(logging, LOG_LEVEL))
        sublogger.propagate = True  # Will propagate to the scraper logger
        
        # Store in our logger cache
        _loggers[component] = sublogger
    
    # Return the main application logger
    return get_logger(LogComponent.APP)

def get_logger(component=LogComponent.APP):
    """Get a logger for a specific component.
    
    Args:
        component: One of the LogComponent constants or a string name
        
    Returns:
        A logger configured for the specified component
    """
    if component in _loggers:
        return _loggers[component]
    
    # If the logger doesn't exist yet, create it
    logger = logging.getLogger(component)
    _loggers[component] = logger
    
    return logger

def log_data_metrics(logger, operation, metrics, level=logging.INFO, **kwargs):
    """Log metrics for a data processing operation.
    
    Args:
        logger: The logger to use
        operation: The name of the operation being measured
        metrics: Dictionary of metrics
        level: The log level to use
        **kwargs: Additional log context data
    """
    extra = {
        'operation': operation,
        'data_metrics': metrics
    }
    extra.update(kwargs)
    
    logger.log(level, f"{operation} metrics: {json.dumps(metrics)}", extra=extra)

def get_caller_info():
    """Get information about the calling function."""
    # Get the frame of the caller's caller
    frame = inspect.currentframe().f_back.f_back
    
    # Extract information
    func_name = frame.f_code.co_name
    filename = os.path.basename(frame.f_code.co_filename)
    lineno = frame.f_lineno
    
    return {
        'function': func_name,
        'file': filename,
        'line': lineno
    }

def log_function_call(func):
    """Decorator to log function calls.
    
    Usage:
        @log_function_call
        def my_function(arg1, arg2):
            # Function body
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Get the appropriate logger for this module
        module_name = func.__module__
        component = module_name.split('.')[-1] if '.' in module_name else LogComponent.APP
        logger = get_logger(component)
        
        # Log the call
        arg_str = ', '.join([str(a) for a in args] + [f"{k}={v}" for k, v in kwargs.items()])
        logger.debug(f"CALL {func.__name__}({arg_str})")
        
        start_time = datetime.now()
        try:
            result = func(*args, **kwargs)
            logger.debug(f"RETURN {func.__name__} - Duration: {datetime.now() - start_time}")
            return result
        except Exception as e:
            logger.exception(f"ERROR in {func.__name__}: {str(e)}")
            raise
            
    return wrapper