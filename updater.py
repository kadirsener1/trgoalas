#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
İNA TV M3U8 Link Toplayıcı ve GitHub Otomatik Güncelleyici
Yazar: Auto M3U Updater
Versiyon: 2.0
"""

import re
import os
import sys
import json
import time
import hashlib
import logging
import requests
from datetime import datetime
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

# GitHub kütüphanesi
try:
    from github import Github, GithubException
    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False
    print("PyGithub yüklü değil. GitHub güncellemesi yapılmayacak.")

# Selenium (JavaScript renderı için)
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("Selenium yüklü değil. Sadece requests kullanılacak.")

# =====================================================
# YAPILANDIRMA
# =====================================================
CONFIG = {
    "TARGET_SITE": "https://inattv1289.xyz/",
    "M3U_FILE": "inattv_playlist.m3u",
    "STATE_FILE": "channel_state.json",
    "LOG_FILE": "updater.log",
    
    # GitHub Ayarları
    "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", "YOUR_GITHUB_TOKEN"),
    "GITHUB_REPO": os.environ.get("GITHUB_REPO", "username/repo-name"),
    "GITHUB_BRANCH": "main",
    "GITHUB_M3U_PATH": "inattv_playlist.m3u",
    
    # Tarama Ayarları
    "REQUEST_TIMEOUT": 30,
    "REQUEST_DELAY": 2,
    "MAX_RETRIES": 3,
    
    # M3U Header Ayarları
    "PLAYLIST_NAME": "INA TV Playlist",
    "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# =====================================================
# LOGGING AYARI
# =====================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(CONFIG["LOG_FILE"], encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# =====================================================
# YARDIMCI FONKSİYONLAR
# =====================================================

def get_headers():
    """HTTP istek başlıkları"""
    return {
        "User-Agent": CONFIG["USER_AGENT"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": CONFIG["TARGET_SITE"],
    }


def load_state():
    """Önceki durumu yükle"""
    if os.path.exists(CONFIG["STATE_FILE"]):
        try:
            with open(CONFIG["STATE_FILE"], "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Durum dosyası yüklenemedi: {e}")
    return {}


def save_state(state):
    """Mevcut durumu kaydet"""
    try:
        with open(CONFIG["STATE_FILE"], "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        logger.info("Durum dosyası kaydedildi.")
    except Exception as e:
        logger.error(f"Durum dosyası kaydedilemedi: {e}")


def url_hash(url):
    """URL için hash oluştur"""
    return hashlib.md5(url.encode()).hexdigest()


# =====================================================
# M3U8 LINK TOPLAYICI
# =====================================================

class M3U8Scraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(get_headers())
        self.found_channels = {}
        self.driver = None
    
    def setup_selenium(self):
        """Selenium WebDriver ayarla"""
        if not SELENIUM_AVAILABLE:
            return False
        
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument(f"--user-agent={CONFIG['USER_AGENT']}")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            # Log ayarları - gereksiz çıktıları gizle
            chrome_options.add_argument("--log-level=3")
            chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            logger.info("Selenium WebDriver başarıyla başlatıldı.")
            return True
        except Exception as e:
            logger.error(f"Selenium başlatılamadı: {e}")
            return False
    
    def close_selenium(self):
        """Selenium'u kapat"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Selenium kapatıldı.")
            except:
                pass
    
    def extract_m3u8_from_text(self, text):
        """Metinden m3u8 linklerini çıkar"""
        patterns = [
            r'https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*',
            r'https?://[^\s\'"<>]+/hls/[^\s\'"<>]+',
            r'https?://[^\s\'"<>]+/live/[^\s\'"<>]+\.m3u8[^\s\'"<>]*',
            r'https?://[^\s\'"<>]+/stream[^\s\'"<>]+\.m3u8[^\s\'"<>]*',
            r'https?://[^\s\'"<>]+/playlist\.m3u8[^\s\'"<>]*',
            r'https?://[^\s\'"<>]+/index\.m3u8[^\s\'"<>]*',
            r'source\s*:\s*["\']?(https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*)',
            r'file\s*:\s*["\']?(https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*)',
            r'src\s*=\s*["\']?(https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*)',
        ]
        
        links = set()
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                # Temizle
                match = match.strip("'\"\\")
                if '.m3u8' in match.lower() or '/hls/' in match.lower():
                    links.add(match)
        
        return links
    
    def get_page_with_requests(self, url):
        """Sayfayı requests ile al"""
        for attempt in range(CONFIG["MAX_RETRIES"]):
            try:
                response = self.session.get(
                    url, 
                    timeout=CONFIG["REQUEST_TIMEOUT"],
                    verify=False
                )
                response.raise_for_status()
                return response.text
            except requests.exceptions.SSLError:
                try:
                    response = self.session.get(
                        url, 
                        timeout=CONFIG["REQUEST_TIMEOUT"],
                        verify=False
                    )
                    return response.text
                except Exception as e:
                    logger.warning(f"SSL hatası (deneme {attempt+1}): {e}")
            except Exception as e:
                logger.warning(f"İstek hatası (deneme {attempt+1}): {e}")
                if attempt < CONFIG["MAX_RETRIES"] - 1:
                    time.sleep(CONFIG["REQUEST_DELAY"])
        return None
    
    def get_page_with_selenium(self, url, wait_time=5):
        """Sayfayı Selenium ile al (JavaScript desteği)"""
        if not self.driver:
            return None
        
        try:
            self.driver.get(url)
            time.sleep(wait_time)
            
            # Sayfanın tam yüklenmesini bekle
            WebDriverWait(self.driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            # Tüm sayfa kaynağını al
            page_source = self.driver.page_source
            
            # Network trafiğini kontrol et (JavaScript log)
            try:
                logs = self.driver.execute_script("""
                    var performance = window.performance || window.mozPerformance || 
                                     window.msPerformance || window.webkitPerformance || {};
                    var network = performance.getEntries ? performance.getEntries() : [];
                    return network.map(function(e) { return e.name; }).join('\\n');
                """)
                page_source += "\n" + (logs or "")
            except:
                pass
            
            return page_source
        except Exception as e:
            logger.error(f"Selenium sayfa alma hatası: {e}")
            return None
    
    def get_all_page_links(self, base_url, html_content):
        """Sayfadaki tüm linkleri al"""
        soup = BeautifulSoup(html_content, 'html.parser')
        links = set()
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            base_parsed = urlparse(base_url)
            
            # Sadece aynı domain
            if parsed.netloc == base_parsed.netloc:
                links.add(full_url)
        
        return links
    
    def extract_channel_info(self, html_content, url):
        """Kanal bilgilerini çıkar"""
        soup = BeautifulSoup(html_content, 'html.parser')
        channels = []
        
        # Kanal adını bul
        channel_name = "Bilinmeyen Kanal"
        
        # Title tag
        if soup.title:
            channel_name = soup.title.string or channel_name
            channel_name = channel_name.strip()
        
        # H1, H2, H3 tagları
        for tag in ['h1', 'h2', 'h3', '.channel-name', '.title', '.name']:
            element = soup.select_one(tag)
            if element and element.get_text(strip=True):
                channel_name = element.get_text(strip=True)
                break
        
        # Logo bul
        logo_url = ""
        for img_selector in ['img.logo', '.channel-logo img', 'img[alt*="logo"]', 
                              'img[alt*="Logo"]', 'img[src*="logo"]']:
            img = soup.select_one(img_selector)
            if img and img.get('src'):
                logo_url = urljoin(url, img['src'])
                break
        
        # İlk büyük resim
        if not logo_url:
            imgs = soup.find_all('img')
            for img in imgs:
                src = img.get('src', '')
                if src and not src.endswith('.svg'):
                    logo_url = urljoin(url, src)
                    break
        
        return channel_name, logo_url
    
    def scrape_site(self):
        """Ana siteyi tara"""
        logger.info(f"Site taranıyor: {CONFIG['TARGET_SITE']}")
        
        # Selenium kur
        has_selenium = self.setup_selenium()
        
        try:
            all_m3u8_links = {}
            visited_urls = set()
            urls_to_visit = [CONFIG["TARGET_SITE"]]
            
            while urls_to_visit:
                current_url = urls_to_visit.pop(0)
                
                if current_url in visited_urls:
                    continue
                    
                visited_urls.add(current_url)
                logger.info(f"Ziyaret ediliyor: {current_url}")
                
                # Önce requests ile dene
                html_content = self.get_page_with_requests(current_url)
                
                # JavaScript gerekliyse Selenium kullan
                if has_selenium:
                    selenium_content = self.get_page_with_selenium(current_url)
                    if selenium_content:
                        # İkisini birleştir
                        combined = (html_content or "") + "\n" + selenium_content
                    else:
                        combined = html_content or ""
                else:
                    combined = html_content or ""
                
                if not combined:
                    continue
                
                # M3U8 linkleri bul
                m3u8_links = self.extract_m3u8_from_text(combined)
                
                if m3u8_links:
                    channel_name, logo_url = self.extract_channel_info(
                        html_content or combined, current_url
                    )
                    
                    for link in m3u8_links:
                        logger.info(f"  ✅ M3U8 bulundu: {link}")
                        
                        if current_url not in all_m3u8_links:
                            all_m3u8_links[current_url] = {
                                "channel_name": channel_name,
                                "logo": logo_url,
                                "page_url": current_url,
                                "m3u8_url": link,
                                "found_at": datetime.now().isoformat()
                            }
                
                # Alt sayfaları bul (sadece ana sayfa için)
                if current_url == CONFIG["TARGET_SITE"] and html_content:
                    sub_links = self.get_all_page_links(current_url, html_content)
                    for link in sub_links:
                        if link not in visited_urls and len(visited_urls) < 100:
                            urls_to_visit.append(link)
                
                time.sleep(CONFIG["REQUEST_DELAY"])
            
            self.found_channels = all_m3u8_links
            logger.info(f"Toplam {len(all_m3u8_links)} kanal/link bulundu.")
            return all_m3u8_links
            
        finally:
            self.close_selenium()


# =====================================================
# M3U DOSYA YÖNETİCİSİ
# =====================================================

class M3UManager:
    def __init__(self, filepath):
        self.filepath = filepath
        self.channels = {}
        self.non_target_lines = []
        self.target_identifier = "inattv"
        
    def parse_existing_m3u(self):
        """Mevcut M3U dosyasını parse et"""
        if not os.path.exists(self.filepath):
            logger.info("M3U dosyası bulunamadı, yeni oluşturulacak.")
            return {}, []
        
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(self.filepath, "r", encoding="latin-1") as f:
                lines = f.readlines()
        
        channels = {}
        non_target = []
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Header
            if line.startswith('#EXTM3U'):
                i += 1
                continue
            
            # EXTINF satırı
            if line.startswith('#EXTINF'):
                extinf_line = line
                
                # Sonraki satır URL olmalı
                if i + 1 < len(lines):
                    url_line = lines[i + 1].strip()
                    
                    # Bu site linki mi?
                    is_target = (
                        self.target_identifier in url_line.lower() or
                        'inattv' in url_line.lower() or
                        self._is_target_channel(extinf_line)
                    )
                    
                    if is_target and url_line.startswith('http'):
                        channel_id = self._extract_channel_id(extinf_line)
                        channels[channel_id] = {
                            "extinf": extinf_line,
                            "url": url_line,
                            "is_target": True
                        }
                        i += 2
                        continue
                    else:
                        # Farklı kaynak - olduğu gibi bırak
                        non_target.append(extinf_line + "\n")
                        if i + 1 < len(lines):
                            non_target.append(lines[i + 1])
                        i += 2
                        continue
            
            i += 1
        
        logger.info(f"Mevcut M3U: {len(channels)} hedef kanal, "
                   f"{len(non_target)//2} diğer kanal")
        return channels, non_target
    
    def _is_target_channel(self, extinf_line):
        """Bu kanalın hedef siteden mi olduğunu kontrol et"""
        target_markers = ['inattv', 'ina tv', 'inatv']
        extinf_lower = extinf_line.lower()
        return any(marker in extinf_lower for marker in target_markers)
    
    def _extract_channel_id(self, extinf_line):
        """EXTINF satırından kanal ID çıkar"""
        # tvg-id
        tvg_id = re.search(r'tvg-id="([^"]*)"', extinf_line)
        if tvg_id and tvg_id.group(1):
            return f"tvg:{tvg_id.group(1)}"
        
        # Kanal adı (son kısım)
        name_match = re.search(r',(.+)$', extinf_line)
        if name_match:
            name = name_match.group(1).strip()
            return f"name:{name.lower().replace(' ', '_')}"
        
        return f"hash:{url_hash(extinf_line)}"
    
    def build_extinf(self, channel_data):
        """EXTINF satırı oluştur"""
        name = channel_data.get("channel_name", "Unknown Channel")
        logo = channel_data.get("logo", "")
        page_url = channel_data.get("page_url", "")
        
        # Kanal adını temizle
        name = name.replace('"', "'").strip()
        if not name:
            name = "INA TV Kanal"
        
        # tvg-id oluştur
        tvg_id = re.sub(r'[^a-zA-Z0-9]', '', name.lower())[:20]
        
        extinf = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}"'
        
        if logo:
            extinf += f' tvg-logo="{logo}"'
        
        extinf += f' group-title="INA TV" source-url="{page_url}"'
        extinf += f',{name}'
        
        return extinf
    
    def update_m3u(self, new_channels_data, existing_channels, non_target_lines):
        """M3U dosyasını güncelle"""
        updated_count = 0
        added_count = 0
        unchanged_count = 0
        
        # Yeni kanalları işle
        updated_channels = dict(existing_channels)  # Mevcut kanalların kopyası
        
        for page_url, channel_data in new_channels_data.items():
            channel_name = channel_data.get("channel_name", "")
            m3u8_url = channel_data.get("m3u8_url", "")
            
            if not m3u8_url:
                continue
            
            # Eşleştirme - isim bazlı
            name_key = f"name:{channel_name.lower().replace(' ', '_')}"
            
            extinf = self.build_extinf(channel_data)
            
            if name_key in updated_channels:
                # Kanal mevcut - sadece URL değiştiyse güncelle
                if updated_channels[name_key]["url"] != m3u8_url:
                    old_url = updated_channels[name_key]["url"]
                    updated_channels[name_key]["url"] = m3u8_url
                    updated_channels[name_key]["extinf"] = extinf
                    logger.info(f"  🔄 Güncellendi: {channel_name}")
                    logger.info(f"     Eski: {old_url}")
                    logger.info(f"     Yeni: {m3u8_url}")
                    updated_count += 1
                else:
                    unchanged_count += 1
            else:
                # Yeni kanal ekle
                updated_channels[name_key] = {
                    "extinf": extinf,
                    "url": m3u8_url,
                    "is_target": True
                }
                logger.info(f"  ➕ Eklendi: {channel_name} -> {m3u8_url}")
                added_count += 1
        
        logger.info(f"\nÖzet: {updated_count} güncellendi, "
                   f"{added_count} eklendi, {unchanged_count} değişmedi")
        
        return updated_channels, non_target_lines, updated_count + added_count > 0
    
    def write_m3u(self, target_channels, non_target_lines):
        """M3U dosyasını yaz"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        content = f'#EXTM3U x-tvg-url="" '
        content += f'playlist-name="{CONFIG["PLAYLIST_NAME"]}" '
        content += f'playlist-desc="INA TV - Son Güncelleme: {timestamp}"\n'
        content += f'# Oluşturulma: {timestamp}\n'
        content += f'# Kaynak: {CONFIG["TARGET_SITE"]}\n\n'
        
        # Diğer kanallar (değiştirilmeden)
        if non_target_lines:
            content += "# ===== DİĞER KANALLAR =====\n"
            content += "".join(non_target_lines)
            content += "\n"
        
        # İNA TV kanalları
        content += "# ===== INA TV KANALLARI =====\n"
        
        sorted_channels = sorted(
            target_channels.items(),
            key=lambda x: x[1].get("extinf", "").lower()
        )
        
        for channel_id, channel_data in sorted_channels:
            extinf = channel_data.get("extinf", "")
            url = channel_data.get("url", "")
            
            if extinf and url:
                content += f"{extinf}\n{url}\n"
        
        # Dosyaya yaz
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                f.write(content)
            
            file_size = os.path.getsize(self.filepath)
            logger.info(f"M3U dosyası yazıldı: {self.filepath} "
                       f"({file_size} bytes, {len(target_channels)} kanal)")
            return True
        except Exception as e:
            logger.error(f"M3U dosyası yazılamadı: {e}")
            return False
    
    def process(self, new_channels_data):
        """Tüm işlemi gerçekleştir"""
        # Mevcut dosyayı oku
        existing_channels, non_target_lines = self.parse_existing_m3u()
        
        # Güncelle
        updated_channels, non_target, has_changes = self.update_m3u(
            new_channels_data, existing_channels, non_target_lines
        )
        
        # Yaz
        if has_changes or not existing_channels:
            success = self.write_m3u(updated_channels, non_target)
            return success, has_changes
        else:
            logger.info("Değişiklik yok, dosya güncellenmeyecek.")
            # Yine de dosyayı yaz (ilk çalıştırma için)
            if not os.path.exists(self.filepath):
                self.write_m3u(updated_channels, non_target)
            return True, False


# =====================================================
# GITHUB YÖNETİCİSİ
# =====================================================

class GitHubManager:
    def __init__(self):
        if not GITHUB_AVAILABLE:
            logger.warning("PyGithub yüklü değil.")
            self.gh = None
            return
        
        token = CONFIG["GITHUB_TOKEN"]
        if not token or token == "YOUR_GITHUB_TOKEN":
            logger.warning("GitHub token ayarlanmamış.")
            self.gh = None
            return
        
        try:
            self.gh = Github(token)
            self.repo = self.gh.get_repo(CONFIG["GITHUB_REPO"])
            logger.info(f"GitHub bağlantısı kuruldu: {CONFIG['GITHUB_REPO']}")
        except Exception as e:
            logger.error(f"GitHub bağlantısı kurulamadı: {e}")
            self.gh = None
    
    def upload_m3u(self, local_file_path, force=False):
        """M3U dosyasını GitHub'a yükle"""
        if not self.gh or not hasattr(self, 'repo'):
            logger.warning("GitHub bağlantısı yok, yükleme atlanıyor.")
            return False
        
        try:
            with open(local_file_path, "r", encoding="utf-8") as f:
                new_content = f.read()
        except Exception as e:
            logger.error(f"Yerel dosya okunamadı: {e}")
            return False
        
        remote_path = CONFIG["GITHUB_M3U_PATH"]
        branch = CONFIG["GITHUB_BRANCH"]
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        commit_message = f"🔄 INA TV playlist güncellendi - {timestamp}"
        
        try:
            # Mevcut dosyayı kontrol et
            try:
                existing_file = self.repo.get_contents(remote_path, ref=branch)
                existing_content = existing_file.decoded_content.decode("utf-8")
                
                if existing_content == new_content and not force:
                    logger.info("GitHub'daki dosya güncel, yükleme atlanıyor.")
                    return True
                
                # Güncelle
                self.repo.update_file(
                    path=remote_path,
                    message=commit_message,
                    content=new_content,
                    sha=existing_file.sha,
                    branch=branch
                )
                logger.info(f"✅ GitHub güncellendi: {remote_path}")
                
            except GithubException as e:
                if e.status == 404:
                    # Dosya yok, oluştur
                    self.repo.create_file(
                        path=remote_path,
                        message=f"🎬 INA TV playlist oluşturuldu - {timestamp}",
                        content=new_content,
                        branch=branch
                    )
                    logger.info(f"✅ GitHub'da yeni dosya oluşturuldu: {remote_path}")
                else:
                    raise
            
            # Raw URL'yi göster
            raw_url = (f"https://raw.githubusercontent.com/"
                      f"{CONFIG['GITHUB_REPO']}/{branch}/{remote_path}")
            logger.info(f"📡 M3U Raw URL: {raw_url}")
            
            return True
            
        except Exception as e:
            logger.error(f"GitHub yükleme hatası: {e}")
            return False
    
    def get_raw_url(self):
        """Raw dosya URL'sini döndür"""
        return (f"https://raw.githubusercontent.com/"
                f"{CONFIG['GITHUB_REPO']}/{CONFIG['GITHUB_BRANCH']}/"
                f"{CONFIG['GITHUB_M3U_PATH']}")


# =====================================================
# GITHUB ACTIONS WORKFLOW OLUŞTURUCU
# =====================================================

def create_github_actions_workflow():
    """GitHub Actions workflow dosyası oluştur"""
    workflow_content = """name: INA TV M3U Auto Update

on:
  schedule:
    # Her 6 saatte bir çalış
    - cron: '0 */6 * * *'
  workflow_dispatch:  # Manuel tetikleme
  push:
    branches: [ main ]
    paths:
      - 'updater.py'

jobs:
  update-playlist:
    runs-on: ubuntu-latest
    
    steps:
    - name: Checkout Repository
      uses: actions/checkout@v4
      with:
        token: ${{ secrets.GITHUB_TOKEN }}
    
    - name: Setup Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    
    - name: Install Chrome
      run: |
        wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
        sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
        sudo apt-get update
        sudo apt-get install -y google-chrome-stable
    
    - name: Install Dependencies
      run: |
        pip install requests beautifulsoup4 selenium webdriver-manager PyGithub
    
    - name: Run Updater
      env:
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        GITHUB_REPO: ${{ github.repository }}
      run: |
        python updater.py
    
    - name: Commit Changes
      run: |
        git config --local user.email "action@github.com"
        git config --local user.name "GitHub Action Bot"
        git add -A
        git diff --staged --quiet || git commit -m "🔄 Auto update: INA TV playlist"
        git push
      env:
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
"""
    
    os.makedirs(".github/workflows", exist_ok=True)
    workflow_path = ".github/workflows/update_playlist.yml"
    
    with open(workflow_path, "w", encoding="utf-8") as f:
        f.write(workflow_content)
    
    logger.info(f"GitHub Actions workflow oluşturuldu: {workflow_path}")
    return workflow_path


# =====================================================
# ANA FONKSİYON
# =====================================================

def main():
    logger.info("=" * 60)
    logger.info("🚀 INA TV M3U Güncelleme Scripti Başlatıldı")
    logger.info(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    
    # GitHub Actions workflow oluştur
    if not os.path.exists(".github/workflows/update_playlist.yml"):
        create_github_actions_workflow()
    
    # Önceki durumu yükle
    state = load_state()
    
    # M3U8 tarayıcısını başlat
    scraper = M3U8Scraper()
    
    # Siteyi tara
    logger.info("\n📡 Site taranıyor...")
    new_channels = scraper.scrape_site()
    
    if not new_channels:
        logger.warning("⚠️ Hiç kanal bulunamadı! Site yapısı değişmiş olabilir.")
        # Test amaçlı manuel kanal ekle
        logger.info("Test modu: Manuel kanal ekleniyor...")
    else:
        logger.info(f"✅ {len(new_channels)} kanal bulundu")
    
    # M3U dosyasını güncelle
    logger.info("\n📝 M3U dosyası güncelleniyor...")
    m3u_manager = M3UManager(CONFIG["M3U_FILE"])
    success, has_changes = m3u_manager.process(new_channels)
    
    if not success:
        logger.error("❌ M3U dosyası güncellenemedi!")
        sys.exit(1)
    
    # GitHub'a yükle
    if has_changes or not state.get("last_upload"):
        logger.info("\n☁️ GitHub'a yükleniyor...")
        github_manager = GitHubManager()
        upload_success = github_manager.upload_m3u(CONFIG["M3U_FILE"])
        
        if upload_success:
            state["last_upload"] = datetime.now().isoformat()
            state["raw_url"] = github_manager.get_raw_url()
            save_state(state)
            
            logger.info(f"\n🎉 İşlem tamamlandı!")
            logger.info(f"📺 IPTV Player URL: {github_manager.get_raw_url()}")
    else:
        logger.info("Değişiklik yok, GitHub güncellenmeyecek.")
    
    logger.info("\n" + "=" * 60)
    logger.info("✅ Script başarıyla tamamlandı")
    logger.info("=" * 60)


if __name__ == "__main__":
    # SSL uyarılarını kapat
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    main()
