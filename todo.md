# Vendor Customer Intelligence Tool

This project is a web-based tool for extracting client/customer information from vendor websites and supplementary sources, then using Grok AI to analyze and summarize the findings.

## Todo List - Core Data Pipeline Fixes

### 1. Enhance Logging Infrastructure
- [x] Implement comprehensive logging for each component
- [x] Create a dedicated logger factory with component-specific loggers
- [x] Update logger.py to write to component-specific log files
- [x] Add detailed logging for each data transformation step
- [x] Implement quantitative metrics (item counts, processing times)
- [ ] Create log analysis utilities to detect pipeline failures

### 2. Fix Vendor Site Scraper
- [ ] Enhance the vendor_site.py scraper to reliably extract customer information
- [ ] Add support for custom scraping rules per vendor
- [ ] Implement fallback strategies with multiple CSS/XPath selectors
- [ ] Add retry logic for network failures
- [ ] Create validation for extracted data
- [ ] Add diagnostic logging for scraping results

### 3. Improve Search Engines Integration
- [ ] Make the search_engines.py more effective at finding customer references
- [ ] Expand search queries beyond basic templates
- [ ] Implement smarter content extraction from search results
- [ ] Add URL deduplication and prioritization
- [ ] Create result validation to filter out irrelevant content
- [ ] Add diagnostic alerts for empty result sets

### 4. Implement Data Validation Checkpoints
- [x] Add validation gates throughout the pipeline
- [x] Create a data validation framework with schema checks
- [x] Implement minimum data requirements for proceeding to the next stage
- [x] Add quality scoring for each data item
- [x] Create alerts for low-quality or missing data
- [x] Implement fallback strategies for insufficient data

### 5. Enhance X.AI API Integration
- [ ] Make the API integration more robust
- [ ] Implement proper error handling for API responses
- [ ] Add conditional logic to prevent API calls with insufficient data
- [ ] Implement context-aware prompting based on data quality
- [ ] Create smarter retry strategies based on error types
- [ ] Add response validation to verify quality

### 6. Introduce Staged Processing with Quality Gates
- [ ] Restructure the pipeline to enforce quality standards
- [ ] Break processing into distinct stages with clear metrics
- [ ] Implement go/no-go decision points between stages
- [ ] Create fallback data enrichment paths when primary sources fail
- [ ] Add user feedback mechanisms for low-confidence results
- [ ] Implement transparent reporting of data quality issues

### 7. Add Alternative Data Sources
- [ ] Expand data collection beyond current sources
- [ ] Integrate additional third-party data sources
- [ ] Implement company LinkedIn profile scraping
- [ ] Add integration with public company directories
- [ ] Create a data source quality ranking system
- [ ] Implement source-specific extraction strategies

### 8. Improve Results Processing
- [ ] Enhance the processing of AI-generated results
- [ ] Implement stricter validation of AI outputs
- [ ] Add confidence scores for each extracted customer
- [ ] Create better deduplication of customer entries
- [ ] Implement smarter URL generation and validation
- [ ] Add explicit source attribution for transparency

### 9. Create Diagnostics Dashboard
- [ ] Build a diagnostics view for system health monitoring
- [ ] Create a diagnostics endpoint for system status
- [ ] Implement visual pipeline flow with health indicators
- [ ] Add real-time processing metrics 
- [ ] Create historical performance tracking
- [ ] Add self-healing recommendations for common issues

### 10. Implement Targeted Feedback Loop
- [ ] Create a mechanism for continuous improvement
- [ ] Add user feedback collection on results quality
- [ ] Implement automatic detection of pipeline failures
- [ ] Create a monitoring system for data source reliability
- [ ] Develop A/B testing capabilities for scraping strategies
- [ ] Build a knowledge base of vendor-specific extraction rules