#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# analyze_site.py - Siteyi analiz et, ne tür linkler var bul

import re
import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings()

TARGET = "https://inattv1289.xyz/"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "tr-TR,tr;q=0.9",
    "Referer": TARGET,
}

session = requests.Session()
session.headers.update(headers)

print("=" * 60)
print(f"Site analiz ediliyor: {TARGET}")
print("=" * 60)

try:
    r = session.get(TARGET, verify=False, timeout=30)
    print(f"Status: {r.status_code}")
    print(f"Content-Type: {r.headers.get('content-type', 'N/A')}")
    print(f"İçerik uzunluğu: {len(r.text)} karakter")
    print()
    
    soup = BeautifulSoup(r.text, 'html.parser')
    
    # Tüm linkleri bul
    print("=== TÜM LİNKLER ===")
    links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text(strip=True)
        links.append((href, text))
        print(f"  [{text}] -> {href}")
    
    print(f"\nToplam link: {len(links)}")
    
    # Script tagları
    print("\n=== SCRIPT İÇERİKLERİ ===")
    scripts = soup.find_all('script')
    print(f"Script sayısı: {len(scripts)}")
    for i, script in enumerate(scripts):
        src = script.get('src', '')
        content = script.string or ''
        if src:
            print(f"  Script {i+1} src: {src}")
        if content and len(content) > 10:
            print(f"  Script {i+1} içerik (ilk 300 karakter):")
            print(f"    {content[:300]}")
    
    # iframe'ler
    print("\n=== IFRAME'LER ===")
    iframes = soup.find_all('iframe')
    for iframe in iframes:
        print(f"  src: {iframe.get('src', 'N/A')}")
        print(f"  id: {iframe.get('id', 'N/A')}")
    
    # Video tagları
    print("\n=== VIDEO TAGLAR ===")
    videos = soup.find_all('video')
    for video in videos:
        print(f"  src: {video.get('src', 'N/A')}")
        sources = video.find_all('source')
        for s in sources:
            print(f"  source: {s.get('src', 'N/A')}")
    
    # Ham HTML'de m3u8 ara
    print("\n=== HAM HTML'DE M3U8 ARA ===")
    m3u8_pattern = re.findall(r'["\']([^"\']+\.m3u8[^"\']*)["\']', r.text)
    if m3u8_pattern:
        for link in set(m3u8_pattern):
            print(f"  ✅ {link}")
    else:
        print("  ❌ Ham HTML'de m3u8 bulunamadı")
    
    # URL pattern ara
    print("\n=== URL PATTERNLERİ ===")
    url_patterns = re.findall(r'https?://[^\s\'"<>]{5,}', r.text)
    unique_urls = set(url_patterns)
    print(f"Bulunan URL sayısı: {len(unique_urls)}")
    for url in list(unique_urls)[:20]:
        print(f"  {url}")
    
    # API endpoint'leri ara
    print("\n=== API ENDPOINT'LERİ ===")
    api_patterns = re.findall(r'["\'/](api|stream|live|channel|hls|video|player)[^\s\'"<>]*', r.text, re.IGNORECASE)
    for p in set(api_patterns)[:20]:
        print(f"  {p}")
    
    # Sayfadaki tüm text
    print("\n=== SAYFA METNİ (ilk 2000 karakter) ===")
    print(r.text[:2000])
    
    # Tüm sayfayı kaydet
    with open("site_html.txt", "w", encoding="utf-8") as f:
        f.write(r.text)
    print("\n✅ Tam HTML 'site_html.txt' dosyasına kaydedildi")
    
except Exception as e:
    print(f"HATA: {e}")
    import traceback
    traceback.print_exc()
