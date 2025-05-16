"""
Test script for URL validation.
"""

import socket
from urllib.parse import urlparse

class URLValidationResult:
    """Contains the result of URL validation with details about why a URL is valid/invalid."""
    
    def __init__(self, url, is_valid=False, structure_valid=False, dns_valid=False, 
                 http_valid=False, cleaned_url=None, reason=None):
        """Initialize validation result."""
        self.original_url = url
        self.is_valid = is_valid
        self.structure_valid = structure_valid
        self.dns_valid = dns_valid
        self.http_valid = http_valid
        self.cleaned_url = cleaned_url
        self.reason = reason
        
    def __bool__(self):
        """Make the validation result usable in boolean contexts."""
        return self.is_valid
        
    def __str__(self):
        """String representation of validation result."""
        if self.is_valid:
            return f"Valid URL: {self.cleaned_url}"
        else:
            return f"Invalid URL: {self.original_url} - {self.reason}"

def validate_url(url, validate_dns=True, validate_http=False, clean_only=False):
    """
    Validate a URL with configurable levels of strictness.
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
    
    # Determine overall validity based on requested validation types
    result.is_valid = result.structure_valid
    if validate_dns:
        result.is_valid = result.is_valid and result.dns_valid
        
    return result

def _validate_url_structure(url):
    """Validate the structure of a URL."""
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
    """Validate that a URL's domain resolves via DNS."""
    if not result.structure_valid:
        # If structure is invalid, DNS will also be invalid
        result.dns_valid = False
        if not result.reason:
            result.reason = "Invalid URL structure"
        return result
    
    domain = result.cleaned_url
    
    # Perform DNS lookup
    try:
        socket.getaddrinfo(domain, None)
        result.dns_valid = True
        return result
    except socket.gaierror:
        # DNS resolution failed
        result.dns_valid = False
        result.reason = "Domain does not resolve"
        print(f"DEBUG: DNS resolution failed for {domain}")
        return result
    except Exception as e:
        # Other exception during DNS resolution
        result.dns_valid = False
        result.reason = f"DNS error: {str(e)}"
        print(f"DEBUG: Error during DNS validation for {domain}: {str(e)}")
        return result

def test_urls():
    """Test a variety of URLs to validate our implementation."""
    test_cases = [
        # Known valid domains
        "google.com",
        "amazon.com",
        "microsoft.com",
        
        # Known invalid domains
        "hitachiamericasandemea.com",  # The problematic domain
        "nonexistentdomainfortesting12345.com",
        "invalid-domain-with-no-tld",
        
        # Edge cases
        "localhost",
        "example.com",
        "a.b",  # Too short domain and TLD
        "a.com",  # Valid but unlikely to exist
        
        # URLs with paths, protocols
        "https://www.python.org/downloads/",
        "http://facebook.com/profile",
        
        # Malformed URLs
        "<script>alert('test')</script>.com",
        "domain with spaces.com",
        "domain@with@special@chars.com"
    ]
    
    print("=== URL VALIDATION TEST RESULTS ===")
    for url in test_cases:
        print("\n--- Testing URL:", url, "---")
        
        # Test structure validation only
        structure_result = validate_url(url, validate_dns=False, validate_http=False)
        print(f"Structure validation: {'PASS' if structure_result.structure_valid else 'FAIL'}")
        print(f"  - Reason: {structure_result.reason}")
        if structure_result.structure_valid:
            print(f"  - Cleaned URL: {structure_result.cleaned_url}")
        
        # Test DNS validation
        dns_result = validate_url(url, validate_dns=True, validate_http=False)
        print(f"DNS validation: {'PASS' if dns_result.dns_valid else 'FAIL'}")
        print(f"  - Reason: {dns_result.reason}")
        
        # Overall validity
        print(f"Overall valid: {dns_result.is_valid}")

if __name__ == "__main__":
    test_urls()