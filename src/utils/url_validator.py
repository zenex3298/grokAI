"""
URL validation utilities for consistent handling of URLs across the application.

This module provides centralized URL validation functions to ensure consistency
in how URLs are validated, cleaned, and processed throughout the application.
"""

import time
import socket
import requests
from urllib.parse import urlparse
from datetime import datetime, timedelta

from src.utils.logger import get_logger, LogComponent, log_data_metrics

# Get a logger for URL validation
logger = get_logger(LogComponent.DATA)

# Cache for DNS validation results to avoid repeated lookups
_dns_cache = {}
_dns_cache_expiry = {}  # Time when cache entries expire
DNS_CACHE_TTL = 3600  # 1 hour cache TTL

# Cache for HTTP validation results
_http_cache = {}
_http_cache_expiry = {}
HTTP_CACHE_TTL = 3600  # 1 hour cache TTL

class URLValidationResult:
    """Contains the result of URL validation with details about why a URL is valid/invalid."""
    
    def __init__(self, url, is_valid=False, structure_valid=False, dns_valid=False, 
                 http_valid=False, cleaned_url=None, reason=None):
        """
        Initialize validation result.
        
        Args:
            url: The original URL that was validated
            is_valid: Overall validity (True if valid, False otherwise)
            structure_valid: Whether the URL has valid structure
            dns_valid: Whether the URL's domain resolves via DNS
            http_valid: Whether the URL returns a valid HTTP response
            cleaned_url: The cleaned version of the URL
            reason: Reason for invalidation if invalid
        """
        self.original_url = url
        self.is_valid = is_valid
        self.structure_valid = structure_valid
        self.dns_valid = dns_valid
        self.http_valid = http_valid
        self.cleaned_url = cleaned_url
        self.reason = reason
        self.validation_time = time.time()
        
    def __bool__(self):
        """Make the validation result usable in boolean contexts."""
        return self.is_valid
        
    def __str__(self):
        """String representation of validation result."""
        if self.is_valid:
            return f"Valid URL: {self.cleaned_url}"
        else:
            return f"Invalid URL: {self.original_url} - {self.reason}"
            
    def to_dict(self):
        """Convert to dictionary."""
        return {
            'original_url': self.original_url,
            'is_valid': self.is_valid,
            'structure_valid': self.structure_valid,
            'dns_valid': self.dns_valid,
            'http_valid': self.http_valid,
            'cleaned_url': self.cleaned_url,
            'reason': self.reason,
            'validation_time': self.validation_time
        }

def validate_url(url, validate_dns=True, validate_http=False, clean_only=False):
    """
    Validate a URL with configurable levels of strictness.
    
    Args:
        url: The URL to validate
        validate_dns: Whether to validate that the domain resolves (default: True)
        validate_http: Whether to validate via HTTP request (default: False)
        clean_only: If True, only clean the URL without validation (default: False)
        
    Returns:
        URLValidationResult object containing validation details
    """
    # If URL is empty or None, return invalid result
    if not url:
        return URLValidationResult(url, is_valid=False, reason="Empty URL")
    
    # Clean and validate URL structure
    result = _validate_url_structure(url)
    
    # If clean_only mode or structure invalid, return early
    if clean_only:
        result.is_valid = True  # In clean_only mode, we consider any cleanable URL valid
        return result
        
    if not result.structure_valid:
        return result  # Structure invalid, no need for further validation
    
    # Validate DNS if requested
    if validate_dns:
        result = _validate_url_dns(result)
        if not result.dns_valid:
            return result  # DNS invalid, no need for HTTP validation
    
    # Validate HTTP if requested
    if validate_http:
        result = _validate_url_http(result)
    
    # Determine overall validity based on requested validation types
    result.is_valid = result.structure_valid
    if validate_dns:
        result.is_valid = result.is_valid and result.dns_valid
    if validate_http:
        result.is_valid = result.is_valid and result.http_valid
        
    return result

def _validate_url_structure(url):
    """
    Validate the structure of a URL.
    
    Args:
        url: The URL to validate
        
    Returns:
        URLValidationResult with structure validation results
    """
    # Remove common prefixes if present
    original_url = url
    url = url.strip()
    
    # Save the original URL with protocol for potential HTTP validation later
    url_with_protocol = url
    if not (url.startswith('http://') or url.startswith('https://')):
        url_with_protocol = f"https://{url}"
    
    # Remove protocols for structure validation
    for prefix in ['http://', 'https://', 'www.']:
        if url.startswith(prefix):
            url = url[len(prefix):]
    
    # Remove path components and parameters
    try:
        parsed = urlparse(f"https://{url}")
        url = parsed.netloc
    except Exception:
        # If parsing fails, URL is invalid
        return URLValidationResult(
            original_url, 
            is_valid=False, 
            structure_valid=False,
            reason="URL parsing failed"
        )
    
    # Ensure URL doesn't contain spaces or special characters
    url = url.lower().replace(' ', '')
    
    # Invalid domain patterns
    invalid_patterns = [
        'example.com', 'localhost', 'test.com', 'sample.com', 
        'domain.com', 'yourdomain.com', 'mysite.com', 'mydomain.com',
        'exampleurl.com', 'testurl.com', 'host.com', 'placeholder.com'
    ]
    
    # Check for invalid patterns
    if url in invalid_patterns:
        return URLValidationResult(
            original_url, 
            is_valid=False, 
            structure_valid=False,
            reason=f"URL contains invalid pattern: {url}"
        )
        
    # Check for common non-URL strings that might slip through
    non_url_indicators = ['<', '>', '"', "'", '{', '}', ';', '\\', '//', '..']
    if any(indicator in url for indicator in non_url_indicators):
        return URLValidationResult(
            original_url, 
            is_valid=False, 
            structure_valid=False,
            reason=f"URL contains invalid characters"
        )
    
    # Validate URL has proper domain structure
    if len(url) < 4 or '.' not in url:
        return URLValidationResult(
            original_url, 
            is_valid=False, 
            structure_valid=False,
            reason=f"URL too short or missing domain extension"
        )
        
    # Ensure there's a valid TLD with at least 2 characters
    tld = url.split('.')[-1]
    if len(tld) < 2:
        return URLValidationResult(
            original_url, 
            is_valid=False, 
            structure_valid=False,
            reason=f"Invalid TLD: {tld}"
        )
        
    # Ensure there's a valid domain name before the TLD
    domain_part = url.split('.')[0]
    if len(domain_part) < 1:
        return URLValidationResult(
            original_url, 
            is_valid=False, 
            structure_valid=False,
            reason=f"Invalid domain name"
        )
    
    # All structure checks passed
    return URLValidationResult(
        original_url,
        is_valid=False,  # Will be updated based on further checks
        structure_valid=True,
        cleaned_url=url,
        reason="Valid structure"
    )

def _validate_url_dns(result):
    """
    Validate that a URL's domain resolves via DNS.
    
    Args:
        result: URLValidationResult from structure validation
        
    Returns:
        Updated URLValidationResult with DNS validation results
    """
    if not result.structure_valid:
        # If structure is invalid, DNS will also be invalid
        result.dns_valid = False
        if not result.reason:
            result.reason = "Invalid URL structure"
        return result
    
    domain = result.cleaned_url
    
    # Check if we have a cached result
    if domain in _dns_cache:
        if _dns_cache_expiry[domain] > datetime.now():
            # Cache is still valid
            result.dns_valid = _dns_cache[domain]
            if not result.dns_valid:
                result.reason = "Domain does not resolve (cached result)"
            return result
        else:
            # Cache has expired, remove it
            del _dns_cache[domain]
            del _dns_cache_expiry[domain]
    
    # Perform DNS lookup
    try:
        socket.getaddrinfo(domain, None)
        _dns_cache[domain] = True
        _dns_cache_expiry[domain] = datetime.now() + timedelta(seconds=DNS_CACHE_TTL)
        result.dns_valid = True
        return result
    except socket.gaierror:
        # DNS resolution failed
        _dns_cache[domain] = False
        _dns_cache_expiry[domain] = datetime.now() + timedelta(seconds=DNS_CACHE_TTL)
        result.dns_valid = False
        result.reason = "Domain does not resolve"
        logger.debug(f"DNS resolution failed for {domain}")
        return result
    except Exception as e:
        # Other exception during DNS resolution
        result.dns_valid = False
        result.reason = f"DNS error: {str(e)}"
        logger.debug(f"Error during DNS validation for {domain}: {str(e)}")
        return result

def _validate_url_http(result, timeout=2):
    """
    Validate a URL by making an HTTP request.
    
    Args:
        result: URLValidationResult from previous validation steps
        timeout: Timeout in seconds for the HTTP request
        
    Returns:
        Updated URLValidationResult with HTTP validation results
    """
    if not result.structure_valid:
        # If structure is invalid, HTTP will also be invalid
        result.http_valid = False
        return result
    
    domain = result.cleaned_url
    url = f"https://{domain}"
    
    # Check if we have a cached result
    if url in _http_cache:
        if _http_cache_expiry[url] > datetime.now():
            # Cache is still valid
            result.http_valid = _http_cache[url]
            if not result.http_valid:
                result.reason = "HTTP validation failed (cached result)"
            return result
        else:
            # Cache has expired, remove it
            del _http_cache[url]
            del _http_cache_expiry[url]
    
    # Perform HTTP validation
    try:
        # Use a HEAD request to minimize data transfer
        response = requests.head(
            url, 
            timeout=timeout, 
            allow_redirects=True,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        
        # Consider 2xx and 3xx status codes as valid
        is_valid = 200 <= response.status_code < 400
        
        # Cache the result
        _http_cache[url] = is_valid
        _http_cache_expiry[url] = datetime.now() + timedelta(seconds=HTTP_CACHE_TTL)
        
        result.http_valid = is_valid
        if not is_valid:
            result.reason = f"HTTP status code: {response.status_code}"
            
        return result
        
    except requests.exceptions.ConnectionError as e:
        # Connection errors
        _http_cache[url] = False
        _http_cache_expiry[url] = datetime.now() + timedelta(seconds=HTTP_CACHE_TTL)
        result.http_valid = False
        
        if "NameResolutionError" in str(e):
            result.reason = "DNS resolution failed during HTTP request"
            logger.debug(f"DNS resolution failed for {url} during HTTP validation")
        else:
            result.reason = f"Connection error: {str(e)}"
            logger.debug(f"Connection error for {url}: {str(e)}")
            
        return result
        
    except requests.exceptions.Timeout:
        # Timeout errors
        _http_cache[url] = False
        _http_cache_expiry[url] = datetime.now() + timedelta(seconds=HTTP_CACHE_TTL)
        result.http_valid = False
        result.reason = f"Request timed out after {timeout}s"
        logger.debug(f"Request timed out for {url} after {timeout}s")
        return result
        
    except requests.exceptions.TooManyRedirects:
        # Redirect loops
        _http_cache[url] = False
        _http_cache_expiry[url] = datetime.now() + timedelta(seconds=HTTP_CACHE_TTL)
        result.http_valid = False
        result.reason = "Too many redirects"
        logger.debug(f"Too many redirects for {url}")
        return result
        
    except requests.exceptions.RequestException as e:
        # Other request exceptions
        _http_cache[url] = False
        _http_cache_expiry[url] = datetime.now() + timedelta(seconds=HTTP_CACHE_TTL)
        result.http_valid = False
        result.reason = f"Request error: {str(e)}"
        logger.debug(f"Request error for {url}: {str(e)}")
        return result
        
    except Exception as e:
        # Catch all other exceptions
        result.http_valid = False
        result.reason = f"Unexpected error: {str(e)}"
        logger.debug(f"Unexpected error validating {url}: {str(e)}")
        return result

def log_validation_stats(urls, validation_results, context=None, log_each_url=True):
    """
    Log statistics about URL validation.
    
    Args:
        urls: List of original URLs
        validation_results: List of URLValidationResult objects
        context: Additional context information for logs
        log_each_url: Whether to log details of each URL (default: True)
    """
    if not urls or not validation_results:
        return
        
    # Compute validation statistics
    total_urls = len(urls)
    structure_valid = sum(1 for r in validation_results if r.structure_valid)
    dns_valid = sum(1 for r in validation_results if r.dns_valid)
    http_valid = sum(1 for r in validation_results if r.http_valid)
    valid_urls = sum(1 for r in validation_results if r.is_valid)
    
    # Group by reasons for invalid URLs
    reason_counts = {}
    for r in validation_results:
        if not r.is_valid and r.reason:
            reason = r.reason
            if reason not in reason_counts:
                reason_counts[reason] = 0
            reason_counts[reason] += 1
    
    # Create metrics
    metrics = {
        'total_urls': total_urls,
        'structure_valid': structure_valid,
        'structure_valid_percent': (structure_valid / total_urls * 100) if total_urls > 0 else 0,
        'dns_valid': dns_valid,
        'dns_valid_percent': (dns_valid / total_urls * 100) if total_urls > 0 else 0,
        'http_valid': http_valid,
        'http_valid_percent': (http_valid / total_urls * 100) if total_urls > 0 else 0,
        'valid_urls': valid_urls,
        'valid_percent': (valid_urls / total_urls * 100) if total_urls > 0 else 0,
        'invalid_reasons': reason_counts
    }
    
    # Add context if provided
    if context:
        metrics.update(context)
    
    # Log the metrics
    log_data_metrics(logger, "url_validation", metrics)
    
    # Log validation summary with appropriate level based on valid percentage
    if valid_urls == 0 and total_urls > 0:
        logger.warning(f"No valid URLs found out of {total_urls} - validation too strict?")
    elif valid_urls / total_urls < 0.5 and total_urls > 5:
        logger.warning(f"Only {valid_urls}/{total_urls} URLs valid ({valid_urls/total_urls*100:.1f}%) - check validation criteria")
    else:
        logger.info(f"URL validation: {valid_urls}/{total_urls} valid ({valid_urls/total_urls*100:.1f}%)")
    
    # Log detailed information about each URL being validated
    if log_each_url:
        logger.info(f"ALL URLs ({total_urls}) being validated:")
        for i, (url, result) in enumerate(zip(urls, validation_results)):
            logger.info(f"  {i+1}. {url} → {result.cleaned_url if result.cleaned_url else 'INVALID'} "
                       f"[structure:{result.structure_valid}, dns:{result.dns_valid}, http:{result.http_valid}]"
                       f"{' - ' + result.reason if result.reason else ''}")
        
    # Log detailed reasons for invalid URLs
    if reason_counts:
        for reason, count in reason_counts.items():
            logger.debug(f"Invalid URL reason: {reason} - {count} occurrences")