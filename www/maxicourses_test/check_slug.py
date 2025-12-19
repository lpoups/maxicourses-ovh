import requests
import sys

URLS = [
    "https://www.coursesu.com/drive-superu-eysines",
    "https://www.coursesu.com/drive-eysines",
    "https://www.coursesu.com/magasin/superu-eysines",
    "https://www.coursesu.com/magasin/super-u-eysines",
    "https://www.coursesu.com/drive-super-u-eysines",
    "https://www.coursesu.com/f-super-u-eysines",
    "https://www.coursesu.com/produits", # control
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
}

for url in URLS:
    try:
        r = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=5)
        print(f"{url} -> {r.status_code} | Final: {r.url}")
    except Exception as e:
        print(f"{url} -> ERROR: {e}")
