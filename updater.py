#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# updater.py - Geliştirilmiş versiyon

import re
import os
import sys
import json
import time
import logging
import requests
import urllib3
from datetime import datetime
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

urllib3.disable_warnings()

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_OK = True
except ImportError:
    SELENIUM_OK = False

try:
    from github import Github
    GITHUB_OK = True
except ImportError:
    GITHUB_OK = False

# Config
TARGET = "https://inattv1289.xyz/"
M3U_FILE = "inattv_playlist.m3u"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("updater.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Referer": TARGET,
}

# ─── M3U8 BULMA ────────────────────────────────────────────

def find_m3u8_in_text(text):
    """Her türlü m3u8 linkini bul"""
    patterns = [
        r'(https?://[^\s\'"<>\)\\]+\.m3u8(?:\?[^\s\'"<>\)\\]*)?)',
        r'(https?://[^\s\'"<>\)\\]+/hls/[^\s\'"<>\)\\]+)',
        r'(https?://[^\s\'"<>\)\\]+/live/[^\s\'"<>\)\\]+\.m3u8[^\s\'"<>\)\\]*)',
        r'(https?://[^\s\'"<>\)\\]+/stream/[^\s\'"<>\)\\]+)',
        r'(https?://[^\s\'"<>\)\\]+/playlist\.m3u8[^\s\'"<>\)\\]*)',
        r'(https?://[^\s\'"<>\)\\]+/index\.m3u8[^\s\'"<>\)\\]*)',
        r'["\']file["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'["\']source["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'["\']src["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'["\']url["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'["\']stream["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'["\']hlsUrl["\']\s*:\s*["\']([^"\']+)["\']',
        r'["\']manifestUrl["\']\s*:\s*["\']([^"\']+)["\']',
        r'hls\.loadSource\(["\']([^"\']+)["\']',
        r'new\s+Hls[^;]+src\s*=\s*["\']([^"\']+)["\']',
        r'player\.src\(\{[^}]*src\s*:\s*["\']([^"\']+)["\']',
        r'videojs\([^)]+\)\s*\.src\(\s*["\']([^"\']+)["\']',
    ]
    
    found = set()
    for p in patterns:
        for match in re.finditer(p, text, re.IGNORECASE):
            url = match.group(1)
            if url and ('m3u8' in url.lower() or 
                       'hls' in url.lower() or 
                       'stream' in url.lower()):
                found.add(url.strip())
    
    return found

def setup_chrome():
    """Chrome driver kur"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-agent={HEADERS['User-Agent']}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    # Network log
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver

def get_network_m3u8(driver):
    """Network trafiğinden m3u8 linklerini al"""
    found = set()
    try:
        logs = driver.get_log("performance")
        for log_entry in logs:
            try:
                msg = json.loads(log_entry["message"])
                method = msg.get("message", {}).get("method", "")
                if "Network.requestWillBeSent" in method:
                    url = (msg.get("message", {})
                              .get("params", {})
                              .get("request", {})
                              .get("url", ""))
                    if url and '.m3u8' in url.lower():
                        found.add(url)
                        log.info(f"    🌐 [Network] {url}")
            except:
                continue
    except Exception as e:
        log.debug(f"Network log hatası: {e}")
    return found

def scan_with_selenium(driver, url, wait=10):
    """Selenium ile sayfayı tara"""
    found = set()
    
    try:
        driver.get(url)
        time.sleep(wait)
        
        # Network'ten al
        network_links = get_network_m3u8(driver)
        found.update(network_links)
        
        # Sayfa kaynağından al
        source_links = find_m3u8_in_text(driver.page_source)
        for link in source_links:
            log.info(f"    📄 [Source] {link}")
        found.update(source_links)
        
        # JavaScript ile player'ları sorgula
        js_links = driver.execute_script("""
            var found = [];
            
            // Video src
            document.querySelectorAll('video, audio').forEach(function(el) {
                if(el.src) found.push(el.src);
                if(el.currentSrc) found.push(el.currentSrc);
            });
            
            // Source tag
            document.querySelectorAll('source').forEach(function(el) {
                if(el.src) found.push(el.src);
            });
            
            // JWPlayer
            try {
                if(typeof jwplayer !== 'undefined') {
                    var players = document.querySelectorAll('[id]');
                    players.forEach(function(p) {
                        try {
                            var jw = jwplayer(p.id);
                            if(jw && jw.getPlaylistItem) {
                                var item = jw.getPlaylistItem();
                                if(item) {
                                    if(item.file) found.push(item.file);
                                    if(item.sources) {
                                        item.sources.forEach(function(s) {
                                            if(s.file) found.push(s.file);
                                        });
                                    }
                                }
                            }
                        } catch(e) {}
                    });
                }
            } catch(e) {}
            
            // VideoJS
            try {
                if(typeof videojs !== 'undefined') {
                    var vjs = videojs.getPlayers();
                    Object.keys(vjs).forEach(function(k) {
                        try {
                            var src = vjs[k].currentSrc();
                            if(src) found.push(src);
                        } catch(e) {}
                    });
                }
            } catch(e) {}
            
            // Clappr
            try {
                if(typeof Clappr !== 'undefined') {
                    found.push('CLAPPR_DETECTED');
                }
            } catch(e) {}
            
            // HLS.js
            try {
                if(typeof Hls !== 'undefined') {
                    found.push('HLS_DETECTED');
                }
            } catch(e) {}
            
            // window değişkenlerinde m3u8 ara
            try {
                var winStr = JSON.stringify(window.playerConfig || {});
                var matches = winStr.match(/https?:\\/\\/[^"']+\\.m3u8[^"']*/g);
                if(matches) found = found.concat(matches);
            } catch(e) {}
            
            return found.filter(function(u) { return u && u.length > 5; });
        """) or []
        
        for link in js_links:
            if link and 'DETECTED' not in link:
                log.info(f"    🎯 [JS] {link}")
                found.add(link)
        
        # iframe'leri tara
        iframes = driver.find_elements("tag name", "iframe")
        for iframe in iframes:
            iframe_src = iframe.get_attribute('src') or ''
            if iframe_src:
                log.info(f"    🖼️ iframe bulundu: {iframe_src}")
                try:
                    driver.switch_to.frame(iframe)
                    time.sleep(3)
                    
                    iframe_source = find_m3u8_in_text(driver.page_source)
                    found.update(iframe_source)
                    
                    iframe_net = get_network_m3u8(driver)
                    found.update(iframe_net)
                    
                    driver.switch_to.default_content()
                except:
                    driver.switch_to.default_content()
        
    except Exception as e:
        log.error(f"Selenium tarama hatası: {e}")
    
    return found

def get_all_channel_pages(driver, base_url):
    """Tüm kanal sayfalarını bul"""
    pages = [base_url]
    
    try:
        driver.get(base_url)
        time.sleep(5)
        
        base_domain = urlparse(base_url).netloc
        
        # Sayfadaki tüm linkleri al
        links = driver.find_elements("tag name", "a")
        for link in links:
            href = link.get_attribute('href') or ''
            if href and urlparse(href).netloc == base_domain:
                if href not in pages:
                    pages.append(href)
        
        log.info(f"Toplam {len(pages)} sayfa bulundu")
    except Exception as e:
        log.error(f"Sayfa listesi alınamadı: {e}")
    
    return pages

def get_channel_name(driver, url):
    """Kanal adını bul"""
    try:
        title = driver.title or ""
        if title:
            # Gereksiz kısımları temizle
            for sep in [' | ', ' - ', ' :: ', ' — ']:
                if sep in title:
                    title = title.split(sep)[0]
            return title.strip()
    except:
        pass
    return f"INA TV {url.split('/')[-1] or 'Ana'}"

# ─── M3U DOSYASI ──────────────────────────────────────────

def load_existing_m3u():
    """Mevcut M3U dosyasını yükle"""
    if not os.path.exists(M3U_FILE):
        return [], []
    
    try:
        with open(M3U_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except:
        return [], []
    
    target_entries = []   # (extinf, url) - bu siteden
    other_entries = []    # (extinf, url) - diğer sitelerden
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if line.startswith("#EXTM3U") or line.startswith("# "):
            i += 1
            continue
        
        if line.startswith("#EXTINF") and i + 1 < len(lines):
            extinf = line
            url = lines[i + 1].strip()
            
            # Bu siteden mi?
            is_ours = (
                "inattv1289" in url or
                "inattv" in url.lower() or
                "inattv" in extinf.lower() or
                'group-title="INA TV"' in extinf
            )
            
            if is_ours:
                target_entries.append((extinf, url))
            else:
                other_entries.append((extinf, url))
            
            i += 2
        else:
            i += 1
    
    log.info(f"Mevcut M3U: {len(target_entries)} INA TV, "
             f"{len(other_entries)} diğer kanal")
    return target_entries, other_entries

def write_m3u(new_channels, other_entries):
    """M3U dosyasını yaz"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    lines = [
        f'#EXTM3U playlist-name="INA TV" '
        f'playlist-desc="Son güncelleme: {now}"\n',
        f'# Otomatik güncellendi: {now}\n',
        f'# Kaynak: {TARGET}\n\n',
    ]
    
    # Diğer kanallar
    if other_entries:
        lines.append("# ===== DİĞER KANALLAR =====\n")
        for extinf, url in other_entries:
            lines.append(f"{extinf}\n{url}\n")
        lines.append("\n")
    
    # INA TV kanalları
    lines.append("# ===== INA TV KANALLARI =====\n")
    for extinf, url in new_channels:
        lines.append(f"{extinf}\n{url}\n")
    
    with open(M3U_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)
    
    log.info(f"✅ M3U yazıldı: {len(new_channels)} INA TV, "
             f"{len(other_entries)} diğer")

def merge_channels(old_target, new_found):
    """
    Yeni bulunan linklerle eskileri birleştir.
    Sadece değişenleri güncelle, diğerlerini bırak.
    """
    # Mevcut URL -> (extinf, url) map
    existing = {}
    for extinf, url in old_target:
        # Kanal adını çıkar
        name_match = re.search(r',(.+)$', extinf)
        name = name_match.group(1).strip() if name_match else ""
        existing[name.lower()] = (extinf, url)
    
    result = []
    changed = 0
    added = 0
    unchanged = 0
    
    for channel_name, m3u8_url, logo in new_found:
        key = channel_name.lower()
        
        # tvg-id
        tvg_id = re.sub(r'[^a-z0-9]', '', key)[:20]
        
        extinf = (
            f'#EXTINF:-1 '
            f'tvg-id="{tvg_id}" '
            f'tvg-name="{channel_name}" '
        )
        if logo:
            extinf += f'tvg-logo="{logo}" '
        extinf += f'group-title="INA TV",{channel_name}'
        
        if key in existing:
            old_extinf, old_url = existing[key]
            if old_url != m3u8_url:
                log.info(f"  🔄 Güncellendi: {channel_name}")
                log.info(f"     Eski URL: {old_url}")
                log.info(f"     Yeni URL: {m3u8_url}")
                result.append((extinf, m3u8_url))
                changed += 1
            else:
                result.append((old_extinf, old_url))
                unchanged += 1
        else:
            log.info(f"  ➕ Yeni kanal: {channel_name} -> {m3u8_url}")
            result.append((extinf, m3u8_url))
            added += 1
    
    log.info(f"Sonuç: {changed} güncellendi, "
             f"{added} eklendi, {unchanged} değişmedi")
    
    return result, (changed + added) > 0

# ─── GITHUB ────────────────────────────────────────────────

def upload_to_github():
    """GitHub'a yükle"""
    if not GITHUB_OK or not GITHUB_TOKEN or not GITHUB_REPO:
        log.warning("GitHub ayarları eksik, yükleme atlanıyor")
        return
    
    try:
        gh = Github(GITHUB_TOKEN)
        repo = gh.get_repo(GITHUB_REPO)
        
        with open(M3U_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = f"🔄 INA TV güncellendi - {now}"
        
        try:
            existing = repo.get_contents(M3U_FILE, ref="main")
            repo.update_file(M3U_FILE, msg, content, existing.sha, branch="main")
            log.info("✅ GitHub güncellendi")
        except Exception as e:
            if "404" in str(e):
                repo.create_file(M3U_FILE, msg, content, branch="main")
                log.info("✅ GitHub'da yeni dosya oluşturuldu")
            else:
                raise
        
        raw = (f"https://raw.githubusercontent.com/"
               f"{GITHUB_REPO}/main/{M3U_FILE}")
        log.info(f"📺 M3U URL: {raw}")
        
    except Exception as e:
        log.error(f"GitHub hatası: {e}")

# ─── ANA FONKSİYON ────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("🚀 INA TV M3U Güncelleyici")
    log.info(f"⏰ {datetime.now()}")
    log.info("=" * 60)
    
    # Mevcut M3U'yu yükle
    old_target, other_entries = load_existing_m3u()
    
    if not SELENIUM_OK:
        log.error("Selenium yüklü değil! pip install selenium webdriver-manager")
        sys.exit(1)
    
    driver = setup_chrome()
    all_found = []  # [(name, m3u8_url, logo), ...]
    
    try:
        # Tüm sayfaları al
        pages = get_all_channel_pages(driver, TARGET)
        log.info(f"\n{len(pages)} sayfa taranacak\n")
        
        for i, page_url in enumerate(pages[:30], 1):
            log.info(f"[{i}/{min(len(pages),30)}] {page_url}")
            
            m3u8_links = scan_with_selenium(driver, page_url, wait=8)
            
            if m3u8_links:
                channel_name = get_channel_name(driver, page_url)
                logo = ""
                
                # Logo bul
                try:
                    imgs = driver.find_elements("tag name", "img")
                    for img in imgs:
                        src = img.get_attribute('src') or ''
                        if src and ('logo' in src.lower() or 
                                   'thumb' in src.lower()):
                            logo = src
                            break
                except:
                    pass
                
                for link in m3u8_links:
                    log.info(f"  ✅ {channel_name}: {link}")
                    all_found.append((channel_name, link, logo))
            else:
                log.info(f"  ❌ Link bulunamadı")
            
            time.sleep(2)
    
    finally:
        driver.quit()
    
    log.info(f"\n{'=' * 60}")
    log.info(f"TOPLAM: {len(all_found)} link bulundu")
    log.info(f"{'=' * 60}\n")
    
    if not all_found:
        log.warning("⚠️ Hiç link bulunamadı!")
        log.warning("analyze_site.py ve network_monitor.py çalıştır")
        return
    
    # Birleştir
    merged, has_changes = merge_channels(old_target, all_found)
    
    # M3U yaz
    write_m3u(merged, other_entries)
    
    # GitHub'a yükle
    if has_changes or not old_target:
        upload_to_github()
    
    log.info("\n✅ Tamamlandı!")

if __name__ == "__main__":
    main()
