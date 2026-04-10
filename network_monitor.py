#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# network_monitor.py - Tüm network isteklerini izle

import re
import json
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

TARGET = "https://inattv1289.xyz/"

def setup_driver():
    """Chrome'u network log ile başlat"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    # Network log aktif et
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    options.add_argument("--enable-logging")
    options.add_argument("--log-level=0")
    
    # Performance log için
    options.add_experimental_option("perfLoggingPrefs", {
        "enableNetwork": True,
        "enablePage": True,
    })
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def get_network_requests(driver):
    """Tüm network isteklerini al"""
    try:
        logs = driver.get_log("performance")
        requests_list = []
        
        for log in logs:
            try:
                log_data = json.loads(log["message"])
                message = log_data.get("message", {})
                method = message.get("method", "")
                
                if "Network.requestWillBeSent" in method:
                    request_url = message.get("params", {}).get("request", {}).get("url", "")
                    if request_url:
                        requests_list.append(request_url)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return requests_list
    except Exception as e:
        print(f"Log alma hatası: {e}")
        return []

def scan_page(driver, url, wait_time=8):
    """Sayfayı tara ve m3u8 bul"""
    print(f"\nSayfa açılıyor: {url}")
    driver.get(url)
    time.sleep(wait_time)
    
    all_urls = []
    m3u8_found = []
    
    # 1. Network logları
    network_urls = get_network_requests(driver)
    all_urls.extend(network_urls)
    
    # 2. Sayfa kaynağı
    page_source = driver.page_source
    
    # 3. JavaScript ile aktif media bul
    try:
        js_sources = driver.execute_script("""
            var sources = [];
            
            // Video elementleri
            document.querySelectorAll('video').forEach(function(v) {
                if(v.src) sources.push(v.src);
                if(v.currentSrc) sources.push(v.currentSrc);
            });
            
            // Source elementleri
            document.querySelectorAll('source').forEach(function(s) {
                if(s.src) sources.push(s.src);
            });
            
            // Hls.js veya benzeri player
            if(window.Hls) sources.push('HLS_PLAYER_DETECTED');
            if(window.jwplayer) {
                try {
                    var p = jwplayer();
                    if(p && p.getPlaylistItem) {
                        var item = p.getPlaylistItem();
                        if(item && item.file) sources.push(item.file);
                    }
                } catch(e) {}
            }
            
            // Tüm script içeriklerini tara
            document.querySelectorAll('script').forEach(function(s) {
                var content = s.textContent || s.innerText;
                var matches = content.match(/https?:\\/\\/[^\\s\'"<>]+\\.m3u8[^\\s\'"<>]*/g);
                if(matches) sources = sources.concat(matches);
            });
            
            return sources;
        """)
        if js_sources:
            all_urls.extend(js_sources)
    except Exception as e:
        print(f"  JS hatası: {e}")
    
    # 4. Tüm URL'leri tara
    m3u8_pattern = re.compile(
        r'https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*',
        re.IGNORECASE
    )
    
    # Network URL'lerinde ara
    for url_item in all_urls:
        if '.m3u8' in url_item.lower():
            m3u8_found.append(url_item)
            print(f"  ✅ [Network] M3U8: {url_item}")
    
    # Sayfa kaynağında ara
    page_matches = m3u8_pattern.findall(page_source)
    for match in page_matches:
        if match not in m3u8_found:
            m3u8_found.append(match)
            print(f"  ✅ [Source] M3U8: {match}")
    
    if not m3u8_found:
        print(f"  ❌ M3U8 bulunamadı")
        print(f"  📋 Network URL sayısı: {len(network_urls)}")
        
        # Tüm URL'leri göster (debug)
        print(f"\n  === Bulunan TÜM URL'ler ===")
        shown = set()
        for u in all_urls:
            if u not in shown and len(shown) < 30:
                print(f"    {u}")
                shown.add(u)
        
        # Sayfa başlığı
        print(f"\n  Sayfa başlığı: {driver.title}")
        
        # İframe'leri kontrol et
        iframes = driver.find_elements("tag name", "iframe")
        if iframes:
            print(f"\n  {len(iframes)} iframe bulundu!")
            for iframe in iframes:
                src = iframe.get_attribute('src') or ''
                print(f"    iframe src: {src}")
    
    return list(set(m3u8_found))

# Ana çalıştırma
print("🔍 Network Monitor Başlatılıyor...")
driver = setup_driver()
all_m3u8 = {}

try:
    # Ana sayfa
    m3u8_links = scan_page(driver, TARGET, wait_time=10)
    for link in m3u8_links:
        all_m3u8[link] = TARGET
    
    # Alt sayfalar
    links_on_page = driver.find_elements("tag name", "a")
    sub_urls = []
    
    base_domain = "inattv1289.xyz"
    for link in links_on_page:
        href = link.get_attribute('href') or ''
        if base_domain in href and href not in sub_urls:
            sub_urls.append(href)
    
    print(f"\n{len(sub_urls)} alt sayfa bulundu")
    
    for sub_url in sub_urls[:20]:  # Max 20 sayfa
        sub_m3u8 = scan_page(driver, sub_url, wait_time=8)
        for link in sub_m3u8:
            all_m3u8[link] = sub_url
        time.sleep(2)

finally:
    driver.quit()

# Sonuç
print("\n" + "=" * 60)
print(f"TOPLAM: {len(all_m3u8)} M3U8 linki bulundu")
print("=" * 60)

# M3U dosyası yaz
if all_m3u8:
    with open("test_output.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for i, (link, source) in enumerate(all_m3u8.items(), 1):
            f.write(f"#EXTINF:-1 group-title=\"INA TV\",Kanal {i}\n")
            f.write(f"{link}\n")
    print("✅ test_output.m3u oluşturuldu!")
else:
    print("❌ Hiç link bulunamadı!")
    print("\n💡 Site muhtemelen:")
    print("  1. Cloudflare koruması kullanıyor")
    print("  2. Anti-bot sistemi var")
    print("  3. Linkleri şifreliyor")
    print("  4. Farklı bir API kullanıyor")
