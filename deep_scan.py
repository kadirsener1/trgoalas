#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# deep_scan.py

import re
import time
import requests
import urllib3
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

urllib3.disable_warnings()

TARGET = "https://inattv1289.xyz/"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Referer": TARGET,
}

session = requests.Session()
session.headers.update(headers)

visited = set()
to_visit = [TARGET]
all_m3u8 = {}

def extract_m3u8(text, page_url):
    """Gelişmiş m3u8 arama"""
    found = []
    
    # Tüm olası pattern'ler
    patterns = [
        # Direkt m3u8
        r'(https?://[^\s\'"<>\)]+\.m3u8(?:\?[^\s\'"<>\)]*)?)',
        # HLS stream
        r'(https?://[^\s\'"<>\)]+/hls/[^\s\'"<>\)]+)',
        # Live stream
        r'(https?://[^\s\'"<>\)]+/live/[^\s\'"<>\)]+)',
        # Stream endpoint
        r'(https?://[^\s\'"<>\)]+/stream[^\s\'"<>\)]+)',
        # Playlist
        r'(https?://[^\s\'"<>\)]+/playlist[^\s\'"<>\)]+)',
        # Index
        r'(https?://[^\s\'"<>\)]+/index\.m3u8[^\s\'"<>\)]*)',
        # Encoded URL'ler
        r'(https?%3A%2F%2F[^\s\'"<>\)]+\.m3u8[^\s\'"<>\)]*)',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        found.extend(matches)
    
    # Relative URL'leri absolute yap
    clean = []
    for url in found:
        if url.startswith('http%3A') or url.startswith('https%3A'):
            from urllib.parse import unquote
            url = unquote(url)
        if url.startswith('//'):
            url = 'https:' + url
        elif url.startswith('/'):
            parsed = urlparse(page_url)
            url = f"{parsed.scheme}://{parsed.netloc}{url}"
        clean.append(url)
    
    return list(set(clean))

def get_page(url):
    """Sayfayı al"""
    try:
        r = session.get(url, verify=False, timeout=20)
        return r.text, r.status_code
    except Exception as e:
        print(f"  HATA: {e}")
        return None, None

print(f"Derin tarama başlıyor: {TARGET}\n")

page_count = 0
max_pages = 50

while to_visit and page_count < max_pages:
    url = to_visit.pop(0)
    
    if url in visited:
        continue
    
    visited.add(url)
    page_count += 1
    
    print(f"[{page_count}] Ziyaret: {url}")
    
    html, status = get_page(url)
    if not html:
        continue
    
    print(f"  Status: {status}, Boyut: {len(html)}")
    
    # M3U8 ara
    m3u8_links = extract_m3u8(html, url)
    if m3u8_links:
        for link in m3u8_links:
            print(f"  ✅ M3U8: {link}")
            all_m3u8[link] = url
    
    # Script src'lerini de kontrol et
    soup = BeautifulSoup(html, 'html.parser')
    
    for script in soup.find_all('script', src=True):
        script_url = urljoin(url, script['src'])
        if urlparse(script_url).netloc == urlparse(TARGET).netloc:
            print(f"  📜 Script: {script_url}")
            script_html, _ = get_page(script_url)
            if script_html:
                script_m3u8 = extract_m3u8(script_html, url)
                for link in script_m3u8:
                    print(f"    ✅ Script'te M3U8: {link}")
                    all_m3u8[link] = url
    
    # Aynı domain alt sayfaları
    base_domain = urlparse(TARGET).netloc
    for a in soup.find_all('a', href=True):
        href = urljoin(url, a['href'])
        if urlparse(href).netloc == base_domain and href not in visited:
            to_visit.append(href)
    
    # iframe src'leri
    for iframe in soup.find_all('iframe', src=True):
        iframe_url = urljoin(url, iframe['src'])
        print(f"  🖼️ iframe: {iframe_url}")
        iframe_html, _ = get_page(iframe_url)
        if iframe_html:
            iframe_m3u8 = extract_m3u8(iframe_html, iframe_url)
            for link in iframe_m3u8:
                print(f"    ✅ iframe'de M3U8: {link}")
                all_m3u8[link] = iframe_url
    
    time.sleep(1)

print("\n" + "=" * 60)
print(f"SONUÇ: {len(all_m3u8)} M3U8 linki bulundu")
print("=" * 60)
for link, source in all_m3u8.items():
    print(f"  {link}")
    print(f"    Kaynak: {source}")
