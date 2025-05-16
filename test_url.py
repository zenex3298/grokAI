import requests

url = 'https://hitachiamericasandemea.com/'
print(f"Testing URL: {url}")

try:
    response = requests.head(
        url, 
        timeout=2,
        allow_redirects=True,
        headers={'User-Agent': 'Mozilla/5.0'}
    )
    print(f'Status code: {response.status_code}')
except Exception as e:
    print(f'Error: {str(e)}')