# Vendor Customer Intelligence Tool

This project is a web-based tool for extracting client/customer information from vendor websites and supplementary sources, then using Grok AI to analyze and summarize the findings.

## Todo List

### User Input & Vendor Website Scraping
- Build a single-page form where users enter "Vendor Name." On submission, send the name to your backend.
- In the backend, begin by scraping the vendor's website:
  - Look for a scrolling bar of logos.
  - Check for a case studies, customer success, or "customers" page (e.g., /customers.html).

### Supplemental Data Extraction
- Use a scraper (BeautifulSoup or similar) to fetch additional pages where the vendor might display clients.
- In parallel, query additional sources:
  - Search [https://www.featuredcustomers.com/](https://www.featuredcustomers.com/)
  - Use Google search for queries like "has chosen [vendor name]" and [vendor name] "case study".
  - For technology-specific info, target vendor-related pages like:
    - Enlyft (e.g., /tech/products/[vendor-specific])
    - PublicWWW
    - NerdyData
    - AppsRunTheWorld
    - BuiltWith
  - Also check review sites (e.g., TrustRadius, Peerspot) where reviewer profiles may reveal customer companies.

### Grok Summarization
- Aggregate all scraped and searched data.
- Directly call Grok's API (using your API key) and pass the collected data so Grok can independently identify and list unique customers.

### Return Results
- Format Grok's output (HTML table with competitor (original vendor name) customer names and customer website) and send this back to the frontend.
- Example output format:

| Competitor | Customer name           | Customer URL           |
|------------|-------------------------|------------------------|
| Taskade    | Booking.com             | booking.com            |
| Taskade    | Verizon                 | verizon.com            |
| Taskade    | TransferWise            | transferwise.com       |
| Taskade    | Sony                    | sony.com               |
| Taskade    | Starbucks               | starbucks.com          |
| Taskade    | Indeed                  | indeed.com             |
| Taskade    | Yamaha                  | yamaha.com             |
| Taskade    | 3M                      | 3m.com                 |
| Taskade    | Dentsu                  | dentsu.com             |
| Taskade    | Backblaze               | backblaze.com          |
| Taskade    | Nike                    | nike.com               |
| Taskade    | Netflix                 | netflix.com            |
| Taskade    | Airbnb                  | airbnb.com             |
| Taskade    | RedBull                 | redbull.com            |
| Taskade    | Blizzard Entertainment  | blizzard.com           |
| Taskade    | Adobe                   | adobe.com              |