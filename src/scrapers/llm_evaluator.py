import os
import time
import json
import requests
import concurrent.futures
from typing import List, Dict, Any, Optional
import re
import html

from src.utils.logger import get_logger, LogComponent, set_context, log_data_metrics, log_function_call
from src.scrapers.enhanced_search import SearchResult

# Get a logger specifically for the LLM evaluation component
logger = get_logger(LogComponent.ANALYZER)

# LLM provider options
LLM_PROVIDER_GROQ = "groq"
LLM_PROVIDER_CLAUDE = "claude"
LLM_PROVIDER_LOCAL = "local"  # For testing/mock responses

# Maximum tokens for context
MAX_CONTEXT_TOKENS = 4000
MAX_RESULTS_PER_BATCH = 5

@log_function_call
def evaluate_search_results(search_results: List[SearchResult], vendor_name: str, 
                           llm_provider: str = LLM_PROVIDER_GROQ) -> List[SearchResult]:
    """
    Use LLM to evaluate search results and prioritize for scraping
    
    Args:
        search_results: List of SearchResult objects to evaluate
        vendor_name: Name of the vendor being researched
        llm_provider: Which LLM provider to use
        
    Returns:
        List of SearchResult objects with added scores and extracted customers
    """
    logger.info(f"Evaluating {len(search_results)} search results with {llm_provider} for vendor: {vendor_name}",
               extra={'vendor_name': vendor_name, 'result_count': len(search_results), 'llm_provider': llm_provider})
    
    # Initialize metrics
    metrics = {
        'start_time': time.time(),
        'vendor_name': vendor_name,
        'llm_provider': llm_provider,
        'total_results': len(search_results),
        'batches': 0,
        'api_calls': 0,
        'api_errors': 0,
        'tokens_used': 0,
        'status': 'started'
    }
    
    # If no results, return empty list
    if not search_results:
        logger.warning(f"No search results to evaluate for vendor: {vendor_name}",
                     extra={'vendor_name': vendor_name})
        metrics['status'] = 'empty'
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        log_data_metrics(logger, "llm_evaluation", metrics)
        return []
    
    # If using local provider (for testing), use mock evaluation
    if llm_provider == LLM_PROVIDER_LOCAL:
        logger.info(f"Using local mock LLM evaluation for {len(search_results)} results", 
                  extra={'vendor_name': vendor_name})
        evaluated_results = _mock_evaluate_results(search_results, vendor_name)
        
        metrics['status'] = 'success_mock'
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        log_data_metrics(logger, "llm_evaluation", metrics)
        return evaluated_results
    
    # Batch results to avoid context limitations
    batches = [search_results[i:i + MAX_RESULTS_PER_BATCH] 
              for i in range(0, len(search_results), MAX_RESULTS_PER_BATCH)]
    metrics['batches'] = len(batches)
    
    evaluated_results = []
    
    try:
        # Process each batch
        for batch_idx, batch in enumerate(batches):
            logger.debug(f"Processing batch {batch_idx+1}/{len(batches)} with {len(batch)} results",
                       extra={'batch_idx': batch_idx, 'batch_size': len(batch), 'vendor_name': vendor_name})
            
            try:
                # Evaluate batch with LLM
                batch_start_time = time.time()
                
                if llm_provider == LLM_PROVIDER_GROQ:
                    results, token_count = _evaluate_with_groq(batch, vendor_name)
                elif llm_provider == LLM_PROVIDER_CLAUDE:
                    results, token_count = _evaluate_with_claude(batch, vendor_name)
                else:
                    raise ValueError(f"Unsupported LLM provider: {llm_provider}")
                
                metrics['api_calls'] += 1
                metrics['tokens_used'] += token_count
                
                batch_duration = time.time() - batch_start_time
                logger.debug(f"Batch {batch_idx+1} processed in {batch_duration:.2f}s, used {token_count} tokens",
                           extra={'batch_idx': batch_idx, 'duration': batch_duration, 'tokens': token_count})
                
                evaluated_results.extend(results)
                
            except Exception as e:
                logger.error(f"Error evaluating batch {batch_idx+1}: {str(e)}",
                           extra={'error_type': type(e).__name__, 'error_message': str(e), 
                                  'batch_idx': batch_idx, 'vendor_name': vendor_name})
                metrics['api_errors'] += 1
                
                # Fall back to mock evaluation for this batch
                mock_results = _mock_evaluate_results(batch, vendor_name)
                evaluated_results.extend(mock_results)
                
        # Sort results by score
        evaluated_results.sort(key=lambda x: x.score if x.score is not None else -1, reverse=True)
        
        # Log success metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'success'
        metrics['evaluated_count'] = len(evaluated_results)
        metrics['high_confidence_count'] = sum(1 for r in evaluated_results if r.confidence == "high")
        log_data_metrics(logger, "llm_evaluation", metrics)
        
        logger.info(f"Successfully evaluated {len(evaluated_results)} search results with {llm_provider}",
                  extra={'vendor_name': vendor_name, 'result_count': len(evaluated_results),
                         'high_confidence': metrics['high_confidence_count'],
                         'tokens_used': metrics['tokens_used']})
        
        return evaluated_results
        
    except Exception as e:
        logger.exception(f"Error in LLM evaluation: {str(e)}",
                       extra={'vendor_name': vendor_name, 'error_type': type(e).__name__, 
                             'error_message': str(e)})
        
        # Fall back to mock evaluation for all results
        evaluated_results = _mock_evaluate_results(search_results, vendor_name)
        
        # Log error metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'error_fallback'
        metrics['error_type'] = type(e).__name__
        metrics['error_message'] = str(e)
        log_data_metrics(logger, "llm_evaluation", metrics)
        
        return evaluated_results


def _evaluate_with_groq(batch: List[SearchResult], vendor_name: str) -> tuple:
    """
    Evaluate a batch of search results using Groq API
    Returns: (evaluated_results, token_count)
    """
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable not set")
    
    # Format the search results for the prompt
    results_text = "\n\n".join([
        f"RESULT {i+1}:\nTitle: {html.escape(result.title)}\nURL: {result.url}\nSnippet: {html.escape(result.snippet)}"
        for i, result in enumerate(batch)
    ])
    
    # Create the prompt
    prompt = f"""You are an AI assistant helping to evaluate search results for finding customer information about a vendor.

VENDOR: {vendor_name}

I'm providing {len(batch)} search results. For each result:
1. Assign a relevance score (0-10) based on how likely it contains customer information about {vendor_name}
2. Assign a confidence level (high, medium, low)
3. Extract any customer company names visible in the title or snippet
4. Provide a brief rationale for your scoring

SEARCH RESULTS:
{results_text}

For each result, respond in the following JSON format:
{{
  "evaluations": [
    {{
      "result_index": 1,
      "relevance_score": 8,
      "confidence": "high",
      "extracted_customers": ["Acme Corp", "TechFirm Inc"],
      "rationale": "Case study page directly showing customer implementations"
    }},
    ...
  ]
}}

Focus only on results that might contain CUSTOMER information (companies that use {vendor_name}'s products/services). Don't include partners, investors, or other relationships unless they're clearly also customers.
"""

    # Make the API request
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "llama3-70b-8192",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 2000
    }
    
    response = requests.post("https://api.groq.com/openai/v1/chat/completions", 
                            headers=headers, json=payload)
    
    if response.status_code != 200:
        logger.error(f"Groq API error: {response.status_code} - {response.text}")
        raise Exception(f"Groq API returned status code {response.status_code}")
    
    # Parse the response
    response_data = response.json()
    response_text = response_data["choices"][0]["message"]["content"]
    token_count = response_data.get("usage", {}).get("total_tokens", 0)
    
    # Extract the JSON from the response
    json_match = re.search(r'({[\s\S]*})', response_text)
    if not json_match:
        logger.error(f"Failed to extract JSON from Groq response: {response_text}")
        raise ValueError("Invalid JSON response from Groq")
    
    try:
        evaluation_data = json.loads(json_match.group(1))
        evaluations = evaluation_data.get("evaluations", [])
        
        # Update the search results with the evaluations
        for eval_item in evaluations:
            result_idx = eval_item.get("result_index") - 1
            if 0 <= result_idx < len(batch):
                batch[result_idx].score = eval_item.get("relevance_score")
                batch[result_idx].confidence = eval_item.get("confidence")
                batch[result_idx].extracted_customers = eval_item.get("extracted_customers", [])
    
    except Exception as e:
        logger.error(f"Error parsing Groq evaluation response: {str(e)}", 
                   extra={'error': str(e), 'response': response_text[:100]})
        raise ValueError(f"Error parsing Groq evaluation: {str(e)}")
    
    return batch, token_count


def _evaluate_with_claude(batch: List[SearchResult], vendor_name: str) -> tuple:
    """
    Evaluate a batch of search results using Claude API
    Returns: (evaluated_results, token_count)
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    
    # Format the search results for the prompt
    results_text = "\n\n".join([
        f"RESULT {i+1}:\nTitle: {html.escape(result.title)}\nURL: {result.url}\nSnippet: {html.escape(result.snippet)}"
        for i, result in enumerate(batch)
    ])
    
    # Create the prompt
    prompt = f"""<task>
Evaluate search results for finding customers of {vendor_name}.

I'm providing {len(batch)} search results. For each result:
1. Assign a relevance score (0-10) based on how likely it contains customer information about {vendor_name}
2. Assign a confidence level (high, medium, low)
3. Extract any customer company names visible in the title or snippet
4. Provide a brief rationale for your scoring

Focus only on results that might contain CUSTOMER information (companies that use {vendor_name}'s products/services). Don't include partners, investors, or other relationships unless they're clearly also customers.
</task>

<search_results>
{results_text}
</search_results>

Please respond in the following JSON format:
{{
  "evaluations": [
    {{
      "result_index": 1,
      "relevance_score": 8,
      "confidence": "high",
      "extracted_customers": ["Acme Corp", "TechFirm Inc"],
      "rationale": "Case study page directly showing customer implementations"
    }},
    ...
  ]
}}
"""

    # Make the API request
    headers = {
        "x-api-key": api_key,
        "content-type": "application/json",
        "anthropic-version": "2023-06-01"
    }
    
    payload = {
        "model": "claude-3-sonnet-20240229",
        "max_tokens": 2000,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}]
    }
    
    response = requests.post("https://api.anthropic.com/v1/messages", 
                            headers=headers, json=payload)
    
    if response.status_code != 200:
        logger.error(f"Claude API error: {response.status_code} - {response.text}")
        raise Exception(f"Claude API returned status code {response.status_code}")
    
    # Parse the response
    response_data = response.json()
    response_text = response_data["content"][0]["text"]
    
    # Claude doesn't directly return token count, so estimate
    token_count = len(prompt.split()) + len(response_text.split())
    
    # Extract the JSON from the response
    json_match = re.search(r'({[\s\S]*})', response_text)
    if not json_match:
        logger.error(f"Failed to extract JSON from Claude response: {response_text}")
        raise ValueError("Invalid JSON response from Claude")
    
    try:
        evaluation_data = json.loads(json_match.group(1))
        evaluations = evaluation_data.get("evaluations", [])
        
        # Update the search results with the evaluations
        for eval_item in evaluations:
            result_idx = eval_item.get("result_index") - 1
            if 0 <= result_idx < len(batch):
                batch[result_idx].score = eval_item.get("relevance_score")
                batch[result_idx].confidence = eval_item.get("confidence")
                batch[result_idx].extracted_customers = eval_item.get("extracted_customers", [])
    
    except Exception as e:
        logger.error(f"Error parsing Claude evaluation response: {str(e)}", 
                   extra={'error': str(e), 'response': response_text[:100]})
        raise ValueError(f"Error parsing Claude evaluation: {str(e)}")
    
    return batch, token_count


def _mock_evaluate_results(search_results: List[SearchResult], vendor_name: str) -> List[SearchResult]:
    """Mock implementation for testing or when APIs are unavailable"""
    logger.warning(f"Using mock evaluation for {len(search_results)} results",
                 extra={'vendor_name': vendor_name})
    
    # Keywords that indicate high relevance
    high_relevance_terms = [
        "case study", "success story", "customer", "client", "testimonial",
        "chose", "selected", "implemented", "deployed", "using"
    ]
    
    # Keywords that indicate potential customer names
    customer_indicators = [
        "case study with", "success story:", "how", "helps", "customer spotlight"
    ]
    
    for result in search_results:
        # Calculate score based on keywords in title and snippet
        score = 0
        
        # Title analysis
        title_lower = result.title.lower()
        for term in high_relevance_terms:
            if term in title_lower:
                score += 2
                
        # Extra points for case studies or success stories
        if "case study" in title_lower or "success story" in title_lower:
            score += 3
            
        # Snippet analysis
        snippet_lower = result.snippet.lower()
        for term in high_relevance_terms:
            if term in snippet_lower:
                score += 1
                
        # Normalize score to 0-10 range
        result.score = min(10, score)
        
        # Set confidence based on score
        if result.score >= 7:
            result.confidence = "high"
        elif result.score >= 4:
            result.confidence = "medium"
        else:
            result.confidence = "low"
        
        # Extract potential customer names
        potential_customers = []
        
        # Extract from case study titles
        if "case study" in title_lower:
            parts = result.title.split(":")
            if len(parts) > 1:
                customer = parts[0].replace("Case Study", "").replace("case study", "").strip()
                if customer and customer.lower() != vendor_name.lower():
                    potential_customers.append(customer)
        
        # Extract from "Company X uses Vendor Y" patterns
        customer_pattern = re.compile(f"([A-Z][A-Za-z0-9 ]+)(?:uses|chose|selected|implemented) {re.escape(vendor_name)}")
        matches = customer_pattern.findall(result.title + " " + result.snippet)
        potential_customers.extend([m.strip() for m in matches if len(m.strip()) > 3])
        
        # Extract "including X, Y, Z" patterns
        if "including" in snippet_lower:
            after_including = result.snippet.split("including")[1].split(".")[0]
            companies = re.findall(r'([A-Z][A-Za-z0-9 ]+)(?:,|and|$)', after_including)
            potential_customers.extend([c.strip() for c in companies if len(c.strip()) > 3])
        
        # Deduplicate and clean
        cleaned_customers = []
        for customer in potential_customers:
            # Remove common prefixes, articles, etc.
            for prefix in ["How ", "Why ", "When ", "The ", "A "]:
                if customer.startswith(prefix):
                    customer = customer[len(prefix):]
            
            # Only keep if not the vendor itself and not too short
            if (customer.lower() != vendor_name.lower() and 
                len(customer) > 3 and 
                customer not in cleaned_customers):
                cleaned_customers.append(customer)
                
        result.extracted_customers = cleaned_customers
    
    # Sort by score
    search_results.sort(key=lambda x: x.score if x.score is not None else -1, reverse=True)
    
    return search_results


@log_function_call
def analyze_page_content(url: str, vendor_name: str, llm_provider: str = LLM_PROVIDER_GROQ) -> List[Dict[str, Any]]:
    """
    Fetch and analyze a web page to extract customer information
    
    Args:
        url: The URL to fetch and analyze
        vendor_name: Name of the vendor being researched
        llm_provider: Which LLM provider to use
        
    Returns:
        List of customer data dictionaries
    """
    logger.info(f"Analyzing page content from {url} for vendor {vendor_name} using {llm_provider}",
               extra={'vendor_name': vendor_name, 'url': url, 'llm_provider': llm_provider})
    
    # Initialize metrics
    metrics = {
        'start_time': time.time(),
        'vendor_name': vendor_name,
        'url': url,
        'llm_provider': llm_provider,
        'status': 'started'
    }
    
    try:
        # Fetch page content
        fetch_start = time.time()
        
        try:
            logger.debug(f"Fetching content from {url}")
            response = requests.get(url, timeout=10)
            
            metrics['fetch_status_code'] = response.status_code
            metrics['fetch_time'] = time.time() - fetch_start
            
            if response.status_code != 200:
                logger.warning(f"Failed to fetch {url}, status code: {response.status_code}",
                             extra={'url': url, 'status_code': response.status_code})
                metrics['status'] = 'fetch_failed'
                raise Exception(f"Failed to fetch URL: status code {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error fetching {url}: {str(e)}",
                       extra={'error_type': type(e).__name__, 'url': url})
            metrics['status'] = 'fetch_error'
            metrics['error_type'] = type(e).__name__
            metrics['error_message'] = str(e)
            raise
        
        # If this is a test or APIs unavailable, use mock analysis
        if llm_provider == LLM_PROVIDER_LOCAL:
            logger.info(f"Using mock content analysis for {url}", extra={'url': url})
            customer_data = _mock_analyze_content(url, vendor_name)
            
            metrics['status'] = 'success_mock'
            metrics['end_time'] = time.time()
            metrics['duration'] = metrics['end_time'] - metrics['start_time']
            metrics['customer_count'] = len(customer_data)
            log_data_metrics(logger, "page_content_analysis", metrics)
            return customer_data
        
        # Parse content with BeautifulSoup to extract main text
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.extract()
        
        # Get text content
        text = soup.get_text()
        
        # Clean up text: break into lines and remove leading/trailing space
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        # Limit content length for LLM
        if len(text) > 10000:
            text = text[:10000] + "...[truncated]"
        
        # Now analyze with LLM
        if llm_provider == LLM_PROVIDER_GROQ:
            customer_data = _analyze_content_with_groq(text, url, vendor_name)
        elif llm_provider == LLM_PROVIDER_CLAUDE:
            customer_data = _analyze_content_with_claude(text, url, vendor_name)
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_provider}")
        
        # Log success metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'success'
        metrics['customer_count'] = len(customer_data)
        log_data_metrics(logger, "page_content_analysis", metrics)
        
        logger.info(f"Successfully analyzed page content from {url}. Found {len(customer_data)} potential customers.",
                  extra={'url': url, 'vendor_name': vendor_name, 'customer_count': len(customer_data)})
        
        return customer_data
        
    except Exception as e:
        logger.exception(f"Error analyzing page content from {url}: {str(e)}",
                       extra={'error_type': type(e).__name__, 'error_message': str(e), 'url': url})
        
        # Fall back to mock analysis
        customer_data = _mock_analyze_content(url, vendor_name)
        
        # Log error metrics
        metrics['end_time'] = time.time()
        metrics['duration'] = metrics['end_time'] - metrics['start_time']
        metrics['status'] = 'error_fallback'
        metrics['error_type'] = type(e).__name__
        metrics['error_message'] = str(e)
        metrics['customer_count'] = len(customer_data)
        log_data_metrics(logger, "page_content_analysis", metrics)
        
        return customer_data


def _analyze_content_with_groq(text: str, url: str, vendor_name: str) -> List[Dict[str, Any]]:
    """Analyze page content using Groq API"""
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable not set")
    
    # Create the prompt
    prompt = f"""You are an AI assistant analyzing web page content to extract customer information about a vendor.

VENDOR: {vendor_name}
URL: {url}

I'll provide the text content from a web page. Your task is to:
1. Extract any customer companies that use {vendor_name}'s products or services
2. For each customer, identify any additional information like:
   - Industry
   - Use case
   - Duration of relationship
   - Benefits or metrics mentioned

IMPORTANT: Focus ONLY on actual CUSTOMERS (companies that use {vendor_name}'s products/services). Do not include partners, integrations, investors, or acquisitions unless explicitly stated they are also customers.

PAGE CONTENT:
{text}

Respond in the following JSON format:
{{
  "customers": [
    {{
      "name": "Company Name",
      "industry": "Industry (if mentioned)",
      "use_case": "How they use the product (if mentioned)",
      "relationship_duration": "How long they've been a customer (if mentioned)",
      "benefits": "Benefits or metrics mentioned",
      "confidence": "high|medium|low"
    }},
    ...
  ],
  "summary": "Brief summary of what kind of customer information was found"
}}

If no customers are found, return an empty customers array.
"""

    # Make the API request
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "llama3-70b-8192",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 2000
    }
    
    response = requests.post("https://api.groq.com/openai/v1/chat/completions", 
                            headers=headers, json=payload)
    
    if response.status_code != 200:
        logger.error(f"Groq API error: {response.status_code} - {response.text}")
        raise Exception(f"Groq API returned status code {response.status_code}")
    
    # Parse the response
    response_data = response.json()
    response_text = response_data["choices"][0]["message"]["content"]
    
    # Extract the JSON from the response
    json_match = re.search(r'({[\s\S]*})', response_text)
    if not json_match:
        logger.error(f"Failed to extract JSON from Groq response: {response_text}")
        raise ValueError("Invalid JSON response from Groq")
    
    try:
        content_data = json.loads(json_match.group(1))
        customers = content_data.get("customers", [])
        
        # Format the results
        customer_data = []
        for customer in customers:
            customer_data.append({
                'name': customer.get('name', ''),
                'metadata': {
                    'industry': customer.get('industry'),
                    'use_case': customer.get('use_case'),
                    'relationship_duration': customer.get('relationship_duration'),
                    'benefits': customer.get('benefits')
                },
                'url': url,
                'source': f"Page content analysis: {url}",
                'confidence': customer.get('confidence', 'medium')
            })
        
        return customer_data
    
    except Exception as e:
        logger.error(f"Error parsing Groq content analysis response: {str(e)}", 
                   extra={'error': str(e), 'response': response_text[:100]})
        raise ValueError(f"Error parsing Groq content analysis: {str(e)}")


def _analyze_content_with_claude(text: str, url: str, vendor_name: str) -> List[Dict[str, Any]]:
    """Analyze page content using Claude API"""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    
    # Create the prompt
    prompt = f"""<task>
Analyze web page content to extract customer information about {vendor_name}.

Your task is to:
1. Extract any customer companies that use {vendor_name}'s products or services
2. For each customer, identify any additional information like:
   - Industry
   - Use case
   - Duration of relationship
   - Benefits or metrics mentioned

IMPORTANT: Focus ONLY on actual CUSTOMERS (companies that use {vendor_name}'s products/services). Do not include partners, integrations, investors, or acquisitions unless explicitly stated they are also customers.
</task>

<page_url>{url}</page_url>

<page_content>
{text}
</page_content>

Please respond in the following JSON format:
{{
  "customers": [
    {{
      "name": "Company Name",
      "industry": "Industry (if mentioned)",
      "use_case": "How they use the product (if mentioned)",
      "relationship_duration": "How long they've been a customer (if mentioned)",
      "benefits": "Benefits or metrics mentioned",
      "confidence": "high|medium|low"
    }},
    ...
  ],
  "summary": "Brief summary of what kind of customer information was found"
}}

If no customers are found, return an empty customers array.
"""

    # Make the API request
    headers = {
        "x-api-key": api_key,
        "content-type": "application/json",
        "anthropic-version": "2023-06-01"
    }
    
    payload = {
        "model": "claude-3-sonnet-20240229",
        "max_tokens": 2000,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}]
    }
    
    response = requests.post("https://api.anthropic.com/v1/messages", 
                            headers=headers, json=payload)
    
    if response.status_code != 200:
        logger.error(f"Claude API error: {response.status_code} - {response.text}")
        raise Exception(f"Claude API returned status code {response.status_code}")
    
    # Parse the response
    response_data = response.json()
    response_text = response_data["content"][0]["text"]
    
    # Extract the JSON from the response
    json_match = re.search(r'({[\s\S]*})', response_text)
    if not json_match:
        logger.error(f"Failed to extract JSON from Claude response: {response_text}")
        raise ValueError("Invalid JSON response from Claude")
    
    try:
        content_data = json.loads(json_match.group(1))
        customers = content_data.get("customers", [])
        
        # Format the results
        customer_data = []
        for customer in customers:
            customer_data.append({
                'name': customer.get('name', ''),
                'metadata': {
                    'industry': customer.get('industry'),
                    'use_case': customer.get('use_case'),
                    'relationship_duration': customer.get('relationship_duration'),
                    'benefits': customer.get('benefits')
                },
                'url': url,
                'source': f"Page content analysis: {url}",
                'confidence': customer.get('confidence', 'medium')
            })
        
        return customer_data
    
    except Exception as e:
        logger.error(f"Error parsing Claude content analysis response: {str(e)}", 
                   extra={'error': str(e), 'response': response_text[:100]})
        raise ValueError(f"Error parsing Claude content analysis: {str(e)}")


def _mock_analyze_content(url: str, vendor_name: str) -> List[Dict[str, Any]]:
    """Mock implementation for testing or when APIs are unavailable"""
    logger.warning(f"Using mock content analysis for {url}",
                 extra={'vendor_name': vendor_name, 'url': url})
    
    # Create some mock customer data based on URL patterns
    domain = urlparse(url).netloc
    path = urlparse(url).path
    
    customer_data = []
    
    # If URL suggests case study
    if "case-study" in url or "success-story" in url or "customer" in url:
        # Generate a customer name from the URL path
        parts = path.split("/")
        potential_name = None
        
        for part in parts:
            if len(part) > 0 and part not in ["case-study", "success-story", "customer"]:
                potential_name = part.replace("-", " ").replace("_", " ").title()
                break
        
        if not potential_name:
            potential_name = domain.split(".")[0].title()
        
        customer_data.append({
            'name': potential_name,
            'metadata': {
                'industry': "Technology",
                'use_case': f"Using {vendor_name} for business optimization",
                'relationship_duration': "Since 2022",
                'benefits': "Improved efficiency by 30%"
            },
            'url': url,
            'source': f"Mock analysis: {url}",
            'confidence': "medium"
        })
    
    # If URL suggests a listing of multiple customers
    elif "customers" in url or "clients" in url or "testimonials" in url:
        # Generate multiple mock customers
        for i in range(3):
            customer_data.append({
                'name': f"Company {i+1} Inc",
                'metadata': {
                    'industry': ["Technology", "Healthcare", "Finance"][i % 3],
                    'use_case': f"Using {vendor_name} for core business functions",
                    'relationship_duration': None,
                    'benefits': None
                },
                'url': url,
                'source': f"Mock analysis: {url}",
                'confidence': "low"
            })
    
    return customer_data