"""
Data validation utilities for the vendor customer intelligence tool.

This module provides validation functions to ensure data quality
throughout the processing pipeline.
"""

import json
import time
from src.utils.logger import get_logger, LogComponent, log_data_metrics, set_context

# Get a logger for the data validation component
logger = get_logger(LogComponent.DATA)

class ValidationLevel:
    """Validation strictness levels."""
    LOW = "low"           # Basic validation, allow most data through
    MEDIUM = "medium"     # Standard validation, filter obviously bad data
    HIGH = "high"         # Strict validation, only allow high-quality data
    CRITICAL = "critical" # Only allow data that meets all criteria

class ValidationResult:
    """Result of a validation operation."""
    
    def __init__(self, is_valid=True, data=None, filtered_data=None, reasons=None, metrics=None):
        """
        Initialize a validation result.
        
        Args:
            is_valid: Boolean indicating if the data passed validation
            data: The original data that was validated
            filtered_data: The filtered data after validation
            reasons: List of reasons for validation failures
            metrics: Dictionary of validation metrics
        """
        self.is_valid = is_valid
        self.data = data or []
        self.filtered_data = filtered_data or []
        self.reasons = reasons or []
        self.metrics = metrics or {}
        
    def __bool__(self):
        """Make the validation result usable in boolean contexts."""
        return self.is_valid
        
    def add_reason(self, reason):
        """Add a reason for validation failure."""
        self.reasons.append(reason)
        
    def to_dict(self):
        """Convert the validation result to a dictionary."""
        return {
            'valid': self.is_valid,
            'original_count': len(self.data),
            'filtered_count': len(self.filtered_data),
            'reasons': self.reasons,
            'metrics': self.metrics
        }
        
    def __str__(self):
        """String representation of the validation result."""
        return json.dumps(self.to_dict(), indent=2)

def validate_customer_data(data, vendor_name, min_items=1, level=ValidationLevel.MEDIUM, context=None):
    """
    Validate a list of customer data items.
    
    Args:
        data: List of customer data dictionaries
        vendor_name: Name of the vendor being processed
        min_items: Minimum number of items required (default: 1)
        level: Validation strictness level (default: MEDIUM)
        context: Additional context information
        
    Returns:
        ValidationResult object
    """
    # Set context for logging
    operation_context = {'vendor_name': vendor_name, 'validation_level': level}
    if context:
        operation_context.update(context)
    
    set_context(**operation_context)
    
    # Initialize metrics
    metrics = {
        'start_time': time.time(),
        'total_items': len(data),
        'valid_items': 0,
        'invalid_items': 0,
        'vendor_name': vendor_name,
        'validation_level': level,
        'min_items_required': min_items,
        'validation_type': 'customer_data'
    }
    
    # Create validation result
    result = ValidationResult(data=data)
    
    # Empty data check
    if not data:
        logger.warning(f"Empty customer data for vendor {vendor_name}",
                     extra={'vendor_name': vendor_name})
        result.is_valid = False
        result.add_reason("No customer data provided")
        
        metrics['status'] = 'failed'
        metrics['failure_reason'] = 'empty_data'
        log_data_metrics(logger, "data_validation", metrics)
        return result
    
    # Filter and validate individual items
    valid_items = []
    invalid_reasons = {}
    
    for i, item in enumerate(data):
        item_valid, reason = validate_customer_item(item, vendor_name, level)
        
        if item_valid:
            valid_items.append(item)
            metrics['valid_items'] += 1
        else:
            metrics['invalid_items'] += 1
            if reason not in invalid_reasons:
                invalid_reasons[reason] = 0
            invalid_reasons[reason] += 1
            
            # Log invalid items in debug mode
            logger.debug(f"Invalid customer data item: {reason}",
                        extra={'reason': reason, 'item': item})
    
    # Update the filtered data
    result.filtered_data = valid_items
    
    # Check if we have enough valid items
    if len(valid_items) < min_items:
        result.is_valid = False
        reason = f"Insufficient valid items: {len(valid_items)}/{min_items} required"
        result.add_reason(reason)
        logger.warning(f"Validation failed: {reason}",
                     extra={'vendor_name': vendor_name, 
                            'valid_count': len(valid_items),
                            'required_count': min_items})
    else:
        result.is_valid = True
        logger.info(f"Validation passed with {len(valid_items)} valid items",
                  extra={'vendor_name': vendor_name, 'valid_count': len(valid_items)})
    
    # Add invalid reasons to result
    for reason, count in invalid_reasons.items():
        result.add_reason(f"{reason} ({count} items)")
    
    # Finalize metrics
    metrics['end_time'] = time.time()
    metrics['duration'] = metrics['end_time'] - metrics['start_time']
    metrics['valid_percentage'] = (metrics['valid_items'] / metrics['total_items'] * 100) if metrics['total_items'] > 0 else 0
    metrics['status'] = 'passed' if result.is_valid else 'failed'
    if not result.is_valid:
        metrics['failure_reasons'] = result.reasons
    
    # Add metrics to result
    result.metrics = metrics
    
    # Log validation metrics
    log_data_metrics(logger, "data_validation", metrics)
    
    return result

def validate_customer_item(item, vendor_name, level=ValidationLevel.MEDIUM):
    """
    Validate a single customer data item.
    
    Args:
        item: Customer data dictionary
        vendor_name: Name of the vendor
        level: Validation strictness level
        
    Returns:
        Tuple of (is_valid, reason_if_invalid)
    """
    # Check if item is a dictionary
    if not isinstance(item, dict):
        return False, "Item is not a dictionary"
    
    # Check if name exists
    if 'name' not in item or not item['name']:
        return False, "Missing customer name"
    
    # Validate customer name based on level
    name = item.get('name', '').strip()
    
    # Check for minimum name length
    if level == ValidationLevel.LOW:
        min_name_length = 2
    else:
        min_name_length = 3
        
    if len(name) < min_name_length:
        return False, f"Customer name too short ({len(name)} chars)"
    
    # Name should not be the vendor name
    if name.lower() == vendor_name.lower():
        return False, "Customer name same as vendor name"
    
    # More strict validation for medium and above
    if level in [ValidationLevel.MEDIUM, ValidationLevel.HIGH, ValidationLevel.CRITICAL]:
        # Check for common invalid names
        invalid_patterns = ['logo', 'image', 'untitled', 'customer', 'client', 'partner']
        if any(pattern in name.lower() for pattern in invalid_patterns):
            return False, f"Customer name contains invalid pattern"
            
        # Check for non-company names (likely false positives)
        common_terms = ['case study', 'white paper', 'blog post', 'article', 'download', 'learn more']
        if any(term in name.lower() for term in common_terms):
            return False, f"Customer name appears to be content, not a company"
    
    # High level validation checks URL if available
    if 'url' in item:
        url = item.get('url')
        if not url:
            if level == ValidationLevel.CRITICAL:
                return False, "Missing URL for customer"
        elif len(url) < 4:  # Minimum valid domain length
            return False, f"URL too short ({len(url)} chars)"
        # Check if URL contains at least one dot (for domain TLD)
        elif '.' not in url:
            return False, f"Invalid URL format (missing domain extension)"
    
    # Critical level validation requires source
    if level == ValidationLevel.CRITICAL:
        if 'source' not in item or not item['source']:
            return False, "Missing source information"
    
    # If we get here, the item is valid
    return True, None

def validate_combined_data(vendor_data, featured_data, search_data, vendor_name, min_total=3, level=ValidationLevel.MEDIUM):
    """
    Validate combined data from all sources.
    
    Args:
        vendor_data: List of customer data from vendor site
        featured_data: List of customer data from featured customers
        search_data: List of customer data from search engines
        vendor_name: Name of the vendor
        min_total: Minimum total items required
        level: Validation strictness level
        
    Returns:
        ValidationResult with combined filtered data
    """
    # Set context for logging
    set_context(vendor_name=vendor_name, operation="validate_combined_data")
    
    # Initialize metrics
    metrics = {
        'start_time': time.time(),
        'vendor_name': vendor_name,
        'vendor_data_count': len(vendor_data),
        'featured_data_count': len(featured_data),
        'search_data_count': len(search_data),
        'total_count': len(vendor_data) + len(featured_data) + len(search_data),
        'validation_level': level,
        'min_total_required': min_total
    }
    
    # Validate each data source individually
    vendor_result = validate_customer_data(vendor_data, vendor_name, min_items=0, 
                                          level=level, context={'source': 'vendor_site'})
    featured_result = validate_customer_data(featured_data, vendor_name, min_items=0, 
                                            level=level, context={'source': 'featured_customers'})
    search_result = validate_customer_data(search_data, vendor_name, min_items=0, 
                                          level=level, context={'source': 'search_engines'})
    
    # Combine filtered data
    combined_data = []
    combined_data.extend(vendor_result.filtered_data)
    combined_data.extend(featured_result.filtered_data)
    combined_data.extend(search_result.filtered_data)
    
    # Deduplicate by customer name and ensure valid URLs
    unique_customers = {}
    for item in combined_data:
        name = item['name'].lower()
        # Only include items with valid URLs
        if 'url' in item and item['url'] and len(item['url']) >= 4 and '.' in item['url']:
            if name not in unique_customers:
                unique_customers[name] = item
    
    combined_filtered = list(unique_customers.values())
    
    # Create combined result
    result = ValidationResult(
        data=vendor_data + featured_data + search_data,
        filtered_data=combined_filtered
    )
    
    # Source-specific metrics
    metrics['vendor_valid_count'] = len(vendor_result.filtered_data)
    metrics['featured_valid_count'] = len(featured_result.filtered_data)
    metrics['search_valid_count'] = len(search_result.filtered_data)
    metrics['combined_valid_count'] = len(combined_filtered)
    
    # Check if we have enough total valid items
    if len(combined_filtered) < min_total:
        result.is_valid = False
        reason = f"Insufficient combined valid items: {len(combined_filtered)}/{min_total} required"
        result.add_reason(reason)
        
        # Add individual source reasons if they failed
        if not vendor_result and vendor_data:
            result.reasons.extend([f"Vendor data: {r}" for r in vendor_result.reasons])
        if not featured_result and featured_data:
            result.reasons.extend([f"Featured data: {r}" for r in featured_result.reasons])
        if not search_result and search_data:
            result.reasons.extend([f"Search data: {r}" for r in search_result.reasons])
            
        logger.warning(f"Combined validation failed: {reason}",
                     extra={'vendor_name': vendor_name, 
                            'valid_count': len(combined_filtered),
                            'required_count': min_total})
        metrics['status'] = 'failed'
        metrics['failure_reason'] = reason
    else:
        result.is_valid = True
        logger.info(f"Combined validation passed with {len(combined_filtered)} valid items",
                  extra={'vendor_name': vendor_name, 'valid_count': len(combined_filtered)})
        metrics['status'] = 'passed'
    
    # Finalize metrics
    metrics['end_time'] = time.time()
    metrics['duration'] = metrics['end_time'] - metrics['start_time']
    
    # Add metrics to result
    result.metrics = metrics
    
    # Log validation metrics
    log_data_metrics(logger, "combined_data_validation", metrics)
    
    return result

def is_empty_data(data, min_items=1):
    """
    Quick check if data meets minimum item threshold.
    
    Args:
        data: List of data items
        min_items: Minimum number of items required
        
    Returns:
        Boolean indicating if data is empty or insufficient
    """
    return not data or len(data) < min_items

def get_validation_level_for_source(source_name, default=ValidationLevel.MEDIUM):
    """
    Get the appropriate validation level for a specific data source.
    Different sources have different reliability and require different
    validation strictness.
    
    Args:
        source_name: Name of the data source
        default: Default validation level
        
    Returns:
        ValidationLevel
    """
    levels = {
        'vendor_site': ValidationLevel.MEDIUM,      # Medium trust in vendor site data
        'featured_customers': ValidationLevel.HIGH, # High trust in featured customers data
        'search_engines': ValidationLevel.LOW       # Low trust in search engine data
    }
    
    return levels.get(source_name, default)