#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
INA TV - Gelişmiş M3U8 Scraper
- Tüm kanal sayfalarını tarar
- iframe içindeki m3u8 linklerini bulur
- Sadece geçerli stream linklerini yazar
- VLC ve Referer desteği ekler
"""

import re
import os
import sys
import json
import time
import logging
import requests
import urllib3
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, quote
from bs4 import BeautifulSoup

urllib3.disable_warnings()

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_OK = True
except ImportError:
    SELENIUM_OK = False
    print("❌ Selenium yok! pip install selenium webdriver-manager")
    sys.exit(1)

try:
    from github import Github
    GITHUB_OK = True
except ImportError:
    GITHUB_OK = False

# ════════════════════════════════════════════════
# YAPILANDIRMA
# ════════════════════════════════════════════════

BASE_URL       = "https://inattv1290.xyz/"
CHANNEL_URL    = "https://inattv1290.xyz/channel.html"
M3U_FILE       = "inattv_playlist.m3u"
STATE_FILE     = "channel_state.json"
LOG_FILE       = "updater.log"
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO    = os.environ.get("GITHUB_REPO", "")
GITHUB_BRANCH  = "main"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Geçersiz domain'ler - bu domainlerden gelen m3u8 linkleri atlanır
INVALID_DOMAINS = [
    "bsky.app",
    "video.bsky.app",
    "cdn.bsky.app",
    "twitter.com",
    "twimg.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "dailymotion.com",
    "vimeo.com",
    "example.com",
    "test.com",
    "localhost",
    "127.0.0.1",
]

# Geçerli stream domain'leri (boşsa hepsi kabul edilir)
VALID_STREAM_PATTERNS = [
    r'\.m3u8',
    r'/hls/',
    r'/live/',
    r'/stream',
    r'/playlist\.m3u8',
]

# ════════════════════════════════════════════════
# LOGGING
# ════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ════════════════════════════════════════════════

def is_valid_stream_url(url: str) -> bool:
    """
    URL'nin geçerli bir stream linki olup olmadığını kontrol et.
    Bsky, sosyal medya vb. linkleri filtrele.
    """
    if not url or not url.startswith("http"):
        return False

    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    # Geçersiz domain kontrolü
    for bad in INVALID_DOMAINS:
        if bad in domain:
            log.debug(f"  ⛔ Geçersiz domain atlandı: {url}")
            return False

    # En az bir geçerli pattern içermeli
    url_lower = url.lower()
    has_valid_pattern = any(
        re.search(p, url_lower) for p in VALID_STREAM_PATTERNS
    )

    if not has_valid_pattern:
        log.debug(f"  ⛔ Stream pattern yok: {url}")
        return False

    # Minimum URL uzunluğu
    if len(url) < 20:
        return False

    return True


def extract_m3u8_urls(text: str) -> set:
    """Metinden tüm m3u8 URL'lerini çıkar"""
    patterns = [
        # Direkt m3u8 URL
        r'(https?://[^\s\'"<>\)\\,\]]+\.m3u8(?:\?[^\s\'"<>\)\\,\]]*)?)',
        # Tırnak içi URL
        r'["\']file["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'["\']source["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'["\']src["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'["\']url["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'["\']stream["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'["\']link["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'["\']hls["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'["\']hlsUrl["\']\s*:\s*["\']([^"\']+)["\']',
        r'["\']manifestUrl["\']\s*:\s*["\']([^"\']+)["\']',
        r'["\']streamUrl["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        # Player fonksiyonları
        r'hls\.loadSource\s*\(\s*["\']([^"\']+)["\']',
        r'player\.src\s*\(\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'video\.src\s*\(\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'\.setup\s*\(\s*\{[^}]*file\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        # HLS path pattern
        r'(https?://[^\s\'"<>\)\\,\]]+/hls/[^\s\'"<>\)\\,\]]+)',
        r'(https?://[^\s\'"<>\)\\,\]]+/live/[^\s\'"<>\)\\,\]]+\.m3u8[^\s\'"<>\)]*)',
        r'(https?://[^\s\'"<>\)\\,\]]+/stream[^\s\'"<>\)\\,\]]*\.m3u8[^\s\'"<>\)]*)',
    ]

    found = set()
    for pattern in patterns:
        try:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                url = match.strip().strip("'\"\\")
                if url:
                    found.add(url)
        except Exception:
            continue

    return found


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ════════════════════════════════════════════════
# CHROME DRIVER
# ════════════════════════════════════════════════

def build_driver() -> webdriver.Chrome:
    """Gelişmiş Chrome driver oluştur"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-agent={USER_AGENT}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-web-security")
    options.add_argument("--allow-running-insecure-content")
    options.add_argument("--ignore-certificate-errors")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)

    # Network log
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    # Webdriver tespitini engelle
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
        """
    })

    return driver


def get_network_requests(driver) -> set:
    """Chrome network loglarından m3u8 URL'lerini topla"""
    found = set()
    try:
        logs = driver.get_log("performance")
        for entry in logs:
            try:
                msg = json.loads(entry["message"])
                method = msg.get("message", {}).get("method", "")
                if method in (
                    "Network.requestWillBeSent",
                    "Network.responseReceived",
                ):
                    params = msg["message"].get("params", {})
                    # Request URL
                    req_url = params.get("request", {}).get("url", "")
                    if req_url and ".m3u8" in req_url.lower():
                        found.add(req_url)
                    # Response URL
                    resp_url = params.get("response", {}).get("url", "")
                    if resp_url and ".m3u8" in resp_url.lower():
                        found.add(resp_url)
            except Exception:
                continue
    except Exception as e:
        log.debug(f"Network log hatası: {e}")
    return found


# ════════════════════════════════════════════════
# KANAL LISTESI ÇEKME
# ════════════════════════════════════════════════

def get_channel_list(driver) -> list:
    """
    Site ana sayfasındaki tüm kanal linklerini topla.
    Format: https://inattv1290.xyz/channel.html?id=xxx
    """
    channels = []
    log.info(f"Ana sayfa taranıyor: {BASE_URL}")

    try:
        driver.get(BASE_URL)
        time.sleep(5)

        # Sayfa tam yüklensin
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(3)

        soup = BeautifulSoup(driver.page_source, "html.parser")

        seen = set()

        # Tüm linkleri tara
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            full_url = urljoin(BASE_URL, href)

            # channel.html?id= pattern
            if "channel.html" in full_url and "id=" in full_url:
                if full_url not in seen:
                    seen.add(full_url)

                    # Kanal adını bul
                    name = (
                        a_tag.get("title", "") or
                        a_tag.get_text(strip=True) or
                        a_tag.find("img", alt=True) and a_tag.find("img")["alt"] or
                        ""
                    )

                    # Logo
                    logo = ""
                    img = a_tag.find("img")
                    if img:
                        logo = urljoin(BASE_URL, img.get("src", ""))

                    # ID'yi parse et
                    parsed = urlparse(full_url)
                    channel_id = parse_qs(parsed.query).get("id", [""])[0]

                    if not name:
                        name = channel_id.replace("-", " ").replace("_", " ").title()

                    channels.append({
                        "id": channel_id,
                        "name": name,
                        "url": full_url,
                        "logo": logo,
                    })
                    log.info(f"  📺 Kanal bulundu: {name} ({channel_id})")

        # Eğer hiç bulunamadıysa JavaScript render dene
        if not channels:
            log.warning("A tag ile kanal bulunamadı, JS render deneniyor...")

            js_links = driver.execute_script("""
                var links = [];
                document.querySelectorAll('a[href]').forEach(function(a) {
                    var href = a.href || '';
                    if(href.includes('channel.html') && href.includes('id=')) {
                        var name = a.title || a.textContent || '';
                        var img = a.querySelector('img');
                        var logo = img ? img.src : '';
                        links.push({
                            url: href,
                            name: name.trim(),
                            logo: logo
                        });
                    }
                });
                return links;
            """) or []

            for item in js_links:
                url = item.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    parsed = urlparse(url)
                    channel_id = parse_qs(parsed.query).get("id", [""])[0]
                    name = item.get("name") or channel_id.replace("-", " ").title()
                    channels.append({
                        "id": channel_id,
                        "name": name,
                        "url": url,
                        "logo": item.get("logo", ""),
                    })
                    log.info(f"  📺 [JS] Kanal: {name}")

        log.info(f"\nToplam {len(channels)} kanal bulundu\n")

    except Exception as e:
        log.error(f"Kanal listesi alınamadı: {e}")
        import traceback
        traceback.print_exc()

    return channels


# ════════════════════════════════════════════════
# IFRAME İÇİNDEKİ M3U8 BULMA
# ════════════════════════════════════════════════

def scan_iframe_for_m3u8(driver, iframe_element, parent_url: str) -> set:
    """Tek bir iframe içindeki m3u8 linklerini bul"""
    found = set()

    try:
        driver.switch_to.frame(iframe_element)
        time.sleep(4)

        # 1. Sayfa kaynağı
        source_links = extract_m3u8_urls(driver.page_source)
        for url in source_links:
            if is_valid_stream_url(url):
                log.info(f"      📄 [iframe-source] {url}")
                found.add(url)

        # 2. Network logları
        net_links = get_network_requests(driver)
        for url in net_links:
            if is_valid_stream_url(url):
                log.info(f"      🌐 [iframe-network] {url}")
                found.add(url)

        # 3. JavaScript player sorgusu
        js_result = driver.execute_script("""
            var found = [];

            // Video elementleri
            document.querySelectorAll('video').forEach(function(v) {
                if(v.src && v.src.length > 5) found.push(v.src);
                if(v.currentSrc && v.currentSrc.length > 5) found.push(v.currentSrc);
            });
            document.querySelectorAll('source').forEach(function(s) {
                if(s.src && s.src.length > 5) found.push(s.src);
            });

            // JWPlayer
            try {
                if(typeof jwplayer !== 'undefined') {
                    var allPlayers = document.querySelectorAll('[id]');
                    allPlayers.forEach(function(el) {
                        try {
                            var p = jwplayer(el.id);
                            if(p && typeof p.getPlaylistItem === 'function') {
                                var item = p.getPlaylistItem();
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
                    // Varsayılan player
                    try {
                        var p = jwplayer();
                        var item = p.getPlaylistItem();
                        if(item && item.file) found.push(item.file);
                    } catch(e) {}
                }
            } catch(e) {}

            // VideoJS
            try {
                if(typeof videojs !== 'undefined') {
                    var players = videojs.getPlayers();
                    Object.keys(players).forEach(function(k) {
                        try {
                            var src = players[k].currentSrc();
                            if(src) found.push(src);
                        } catch(e) {}
                    });
                }
            } catch(e) {}

            // Clappr Player
            try {
                if(typeof Clappr !== 'undefined' && window._clapprPlayer) {
                    var src = window._clapprPlayer.options.source;
                    if(src) found.push(src);
                }
            } catch(e) {}

            // FlowPlayer
            try {
                if(typeof flowplayer !== 'undefined') {
                    var fp = flowplayer();
                    if(fp && fp.currentSrc) found.push(fp.currentSrc());
                }
            } catch(e) {}

            // HLS.js - global değişkenler
            try {
                var props = Object.keys(window);
                props.forEach(function(k) {
                    try {
                        var val = window[k];
                        if(val && typeof val === 'object') {
                            var str = JSON.stringify(val);
                            var matches = str.match(/https?:\/\/[^"']+\.m3u8[^"']*/g);
                            if(matches) found = found.concat(matches);
                        }
                    } catch(e) {}
                });
            } catch(e) {}

            // window.streamUrl, window.hlsUrl vb.
            var streamVars = [
                'streamUrl', 'hlsUrl', 'videoUrl', 'streamLink',
                'channelUrl', 'm3u8Url', 'liveUrl', 'playbackUrl',
                'source', 'videoSource', 'streamSource'
            ];
            streamVars.forEach(function(v) {
                try {
                    if(window[v] && typeof window[v] === 'string') {
                        found.push(window[v]);
                    }
                } catch(e) {}
            });

            return found.filter(function(u) {
                return u && typeof u === 'string' && u.startsWith('http');
            });
        """) or []

        for url in js_result:
            if url and is_valid_stream_url(url):
                log.info(f"      🎯 [iframe-js] {url}")
                found.add(url)

        # 4. İç içe iframe'leri de tara
        inner_iframes = driver.find_elements(By.TAG_NAME, "iframe")
        if inner_iframes:
            log.info(f"      🔍 {len(inner_iframes)} iç iframe bulundu")
            for inner_iframe in inner_iframes:
                try:
                    inner_src = inner_iframe.get_attribute("src") or ""
                    log.info(f"        iç iframe src: {inner_src}")
                    inner_found = scan_iframe_for_m3u8(
                        driver, inner_iframe, parent_url
                    )
                    found.update(inner_found)
                except Exception as ie:
                    log.debug(f"        iç iframe hatası: {ie}")

    except Exception as e:
        log.error(f"      iframe tarama hatası: {e}")
    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass

    return found


def scan_channel_page(driver, channel: dict) -> list:
    """
    Bir kanal sayfasını tara ve m3u8 linklerini bul.
    Returns: [(m3u8_url, referer_url), ...]
    """
    page_url = channel["url"]
    log.info(f"\n  🔍 Taranıyor: {channel['name']} -> {page_url}")

    all_m3u8 = set()

    try:
        driver.get(page_url)
        time.sleep(6)

        # Sayfa yüklensin
        try:
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception:
            pass
        time.sleep(3)

        # 1. Ana sayfa kaynağından ara
        source_links = extract_m3u8_urls(driver.page_source)
        for url in source_links:
            if is_valid_stream_url(url):
                log.info(f"    ✅ [page-source] {url}")
                all_m3u8.add(url)

        # 2. Network trafiği
        net_links = get_network_requests(driver)
        for url in net_links:
            if is_valid_stream_url(url):
                log.info(f"    ✅ [network] {url}")
                all_m3u8.add(url)

        # 3. iframe'leri tara (ANA HEDEF)
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        log.info(f"    🖼️ {len(iframes)} iframe bulundu")

        for idx, iframe in enumerate(iframes):
            iframe_src = ""
            try:
                iframe_src = iframe.get_attribute("src") or ""
                iframe_id  = iframe.get_attribute("id") or f"frame_{idx}"
                log.info(f"    iframe[{idx}] id={iframe_id} src={iframe_src}")

                # iframe'e gir ve m3u8 ara
                iframe_links = scan_iframe_for_m3u8(driver, iframe, page_url)
                all_m3u8.update(iframe_links)

                # iframe src'sini de ayrıca tara
                if iframe_src and iframe_src.startswith("http"):
                    try:
                        iframe_page = requests.get(
                            iframe_src,
                            headers={"User-Agent": USER_AGENT,
                                     "Referer": page_url},
                            timeout=10,
                            verify=False
                        )
                        src_links = extract_m3u8_urls(iframe_page.text)
                        for url in src_links:
                            if is_valid_stream_url(url):
                                log.info(f"      ✅ [iframe-req] {url}")
                                all_m3u8.add(url)
                    except Exception:
                        pass

            except Exception as e:
                log.debug(f"    iframe[{idx}] hatası: {e}")
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass

        # 4. JavaScript ile direkt player sorgula
        js_urls = driver.execute_script("""
            var found = [];

            // Video tagları
            document.querySelectorAll('video').forEach(function(v) {
                if(v.src) found.push(v.src);
                if(v.currentSrc) found.push(v.currentSrc);
            });

            // Script içeriklerini tara
            document.querySelectorAll('script').forEach(function(s) {
                var c = s.textContent || '';
                var m = c.match(/https?:\/\/[^\s'"<>\\)]+\.m3u8[^\s'"<>\\)]*/g);
                if(m) found = found.concat(m);
            });

            return found;
        """) or []

        for url in js_urls:
            if url and is_valid_stream_url(url):
                log.info(f"    ✅ [js-direct] {url}")
                all_m3u8.add(url)

    except Exception as e:
        log.error(f"  Sayfa tarama hatası: {e}")

    # Referer ile birlikte döndür
    result = [(url, page_url) for url in all_m3u8]

    if not result:
        log.warning(f"  ❌ {channel['name']} için link bulunamadı")
    else:
        log.info(f"  ✅ {channel['name']}: {len(result)} link bulundu")

    return result


# ════════════════════════════════════════════════
# M3U DOSYA YÖNETİMİ
# ════════════════════════════════════════════════

def load_existing_m3u() -> tuple:
    """
    Mevcut M3U dosyasını parse et.
    Returns: (ina_channels, other_channels)
    ina_channels  = {channel_id: {"extinf": str, "url": str}}
    other_channels = [(extinf_line, url_line), ...]
    """
    if not os.path.exists(M3U_FILE):
        return {}, []

    try:
        with open(M3U_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return {}, []

    ina_channels  = {}
    other_channels = []
    lines = content.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line or line.startswith("#EXTM3U") or line.startswith("# ==="):
            i += 1
            continue

        if line.startswith("#EXTINF") and i + 1 < len(lines):
            extinf_line = line
            url_line = lines[i + 1].strip()

            # Bu siteye ait mi?
            is_ours = (
                "inattv" in url_line.lower() or
                'group-title="INA TV"' in extinf_line or
                "inattv" in extinf_line.lower()
            )

            if is_ours:
                # channel id'yi bul
                tvg_id_match = re.search(r'tvg-id="([^"]*)"', extinf_line)
                key = tvg_id_match.group(1) if tvg_id_match else url_line
                ina_channels[key] = {
                    "extinf": extinf_line,
                    "url": url_line,
                }
            else:
                other_channels.append((extinf_line, url_line))

            i += 2
        else:
            i += 1

    log.info(
        f"Mevcut M3U: {len(ina_channels)} INA TV kanalı, "
        f"{len(other_channels)} diğer kanal"
    )
    return ina_channels, other_channels


def build_extinf(channel: dict, m3u8_url: str, referer_url: str) -> str:
    """
    IPTV uyumlu #EXTINF satırı oluştur.
    VLC ve Referer desteği dahil.
    """
    name    = channel.get("name", "INA TV Kanal").strip()
    logo    = channel.get("logo", "")
    ch_id   = channel.get("id", "")
    tvg_id  = re.sub(r"[^a-z0-9]", "", (ch_id or name).lower())[:30]

    extinf = (
        f'#EXTINF:-1 '
        f'tvg-id="{tvg_id}" '
        f'tvg-name="{name}" '
    )

    if logo:
        extinf += f'tvg-logo="{logo}" '

    extinf += f'group-title="INA TV"'

    # Referer (bazı player'lar bu attribute'u okur)
    if referer_url:
        extinf += f' tvg-url="{referer_url}"'

    extinf += f",{name}"

    return extinf


def write_m3u(ina_channels: dict, other_channels: list):
    """
    M3U dosyasını yaz.
    VLC http-referrer ve http-user-agent direktifleri dahil.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = []

    # ── Header ──────────────────────────────────
    lines.append(
        f'#EXTM3U '
        f'x-tvg-url="" '
        f'playlist-name="INA TV" '
        f'playlist-desc="Son guncelleme: {now}"\n'
    )
    lines.append(f"# Kaynak   : {BASE_URL}\n")
    lines.append(f"# Guncelleme: {now}\n")
    lines.append(f"# Toplam   : {len(ina_channels)} INA TV + {len(other_channels)} diger\n")
    lines.append("\n")

    # ── Diğer kanallar (dokunulmadan) ───────────
    if other_channels:
        lines.append("# ===== DİĞER KANALLAR (değiştirilmedi) =====\n")
        for extinf_line, url_line in other_channels:
            lines.append(f"{extinf_line}\n")
            lines.append(f"{url_line}\n")
        lines.append("\n")

    # ── INA TV kanalları ────────────────────────
    lines.append("# ===== INA TV CANLI YAYINLAR =====\n")

    for key, data in sorted(ina_channels.items(),
                             key=lambda x: x[1].get("extinf", "")):
        extinf  = data["extinf"]
        url     = data["url"]
        referer = data.get("referer", BASE_URL)

        lines.append(f"{extinf}\n")

        # ── VLC Desteği ──────────────────────────
        # #EXTVLCOPT direktifleri VLC ve uyumlu player'larda çalışır
        lines.append(
            f"#EXTVLCOPT:http-referrer={referer}\n"
        )
        lines.append(
            f"#EXTVLCOPT:http-user-agent={USER_AGENT}\n"
        )

        # ── Kodex / Kodi / TiviMate Referer ─────
        # Bazı player'lar URL sonuna |header parametresi ekler
        encoded_ua  = quote(USER_AGENT, safe="")
        encoded_ref = quote(referer, safe="")
        full_url = (
            f"{url}"
            f"|Referer={encoded_ref}"
            f"&User-Agent={encoded_ua}"
        )
        lines.append(f"{full_url}\n")

    # Dosyaya yaz
    with open(M3U_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)

    size_kb = os.path.getsize(M3U_FILE) / 1024
    log.info(
        f"✅ M3U yazıldı: {M3U_FILE} "
        f"({size_kb:.1f} KB, {len(ina_channels)} kanal)"
    )


def merge_and_update(
    old_ina: dict,
    new_found: list,  # [(channel_dict, m3u8_url, referer_url), ...]
) -> tuple:
    """
    Yeni bulunan linklerle eskileri birleştir.
    Sadece değişen linkleri güncelle.
    """
    updated  = dict(old_ina)
    changed  = 0
    added    = 0
    skipped  = 0

    for channel, m3u8_url, referer_url in new_found:
        extinf = build_extinf(channel, m3u8_url, referer_url)

        ch_id  = channel.get("id", "")
        tvg_id = re.sub(r"[^a-z0-9]", "", ch_id.lower())[:30]

        if tvg_id in updated:
            old_url = updated[tvg_id]["url"]
            if old_url == m3u8_url:
                log.info(f"  ⏭️ Değişmedi: {channel['name']}")
                skipped += 1
            else:
                log.info(f"  🔄 Güncellendi: {channel['name']}")
                log.info(f"     Eski: {old_url}")
                log.info(f"     Yeni: {m3u8_url}")
                updated[tvg_id] = {
                    "extinf":  extinf,
                    "url":     m3u8_url,
                    "referer": referer_url,
                }
                changed += 1
        else:
            log.info(f"  ➕ Yeni: {channel['name']} -> {m3u8_url}")
            updated[tvg_id] = {
                "extinf":  extinf,
                "url":     m3u8_url,
                "referer": referer_url,
            }
            added += 1

    has_changes = (changed + added) > 0
    log.info(
        f"\nÖzet: {changed} güncellendi | "
        f"{added} eklendi | {skipped} değişmedi"
    )
    return updated, has_changes


# ════════════════════════════════════════════════
# GITHUB
# ════════════════════════════════════════════════

def upload_github():
    if not GITHUB_OK:
        log.warning("PyGithub yüklü değil")
        return
    if not GITHUB_TOKEN or not GITHUB_REPO:
        log.warning("GITHUB_TOKEN veya GITHUB_REPO ayarlanmamış")
        return

    try:
        gh   = Github(GITHUB_TOKEN)
        repo = gh.get_repo(GITHUB_REPO)

        with open(M3U_FILE, "r", encoding="utf-8") as f:
            content = f.read()

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = f"🔄 INA TV güncellendi - {now}"

        try:
            existing = repo.get_contents(M3U_FILE, ref=GITHUB_BRANCH)
            if existing.decoded_content.decode("utf-8") == content:
                log.info("GitHub zaten güncel, yükleme atlanıyor")
                return
            repo.update_file(
                M3U_FILE, msg, content,
                existing.sha, branch=GITHUB_BRANCH
            )
        except Exception as e:
            if "404" in str(e):
                repo.create_file(M3U_FILE, msg, content, branch=GITHUB_BRANCH)
            else:
                raise

        raw_url = (
            f"https://raw.githubusercontent.com/"
            f"{GITHUB_REPO}/{GITHUB_BRANCH}/{M3U_FILE}"
        )
        log.info(f"✅ GitHub güncellendi")
        log.info(f"📺 M3U URL: {raw_url}")

    except Exception as e:
        log.error(f"GitHub hatası: {e}")


# ════════════════════════════════════════════════
# ANA FONKSİYON
# ════════════════════════════════════════════════

def main():
    log.info("=" * 65)
    log.info("🚀 INA TV M3U8 Scraper Başladı")
    log.info(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"🌐 Hedef: {BASE_URL}")
    log.info("=" * 65)

    # Mevcut M3U'yu yükle
    old_ina, other_channels = load_existing_m3u()

    # Driver başlat
    log.info("\nChrome başlatılıyor...")
    driver = build_driver()

    all_found = []  # [(channel_dict, m3u8_url, referer_url)]

    try:
        # ── Kanal listesini al ───────────────────
        channels = get_channel_list(driver)

        if not channels:
            log.error("❌ Hiç kanal bulunamadı!")
            log.error("Site yapısı değişmiş olabilir.")
            return

        log.info(f"\n{'─'*65}")
        log.info(f"📋 {len(channels)} kanal taranacak")
        log.info(f"{'─'*65}\n")

        # ── Her kanalı tara ──────────────────────
        for idx, channel in enumerate(channels, 1):
            log.info(
                f"[{idx:02d}/{len(channels):02d}] "
                f"{'─'*40}"
            )

            results = scan_channel_page(driver, channel)

            for m3u8_url, referer_url in results:
                all_found.append((channel, m3u8_url, referer_url))

            # Rate limiting
            time.sleep(2)

    finally:
        driver.quit()
        log.info("\nChrome kapatıldı")

    # ── Sonuçları göster ─────────────────────────
    log.info(f"\n{'='*65}")
    log.info(f"📊 TOPLAM: {len(all_found)} M3U8 linki bulundu")
    log.info(f"{'='*65}")

    if not all_found:
        log.error("❌ Hiç link bulunamadı!")
        log.error(
            "Lütfen analyze_site.py çalıştırarak "
            "site yapısını kontrol edin."
        )
        sys.exit(1)

    # ── Birleştir ve güncelle ─────────────────────
    updated_ina, has_changes = merge_and_update(old_ina, all_found)

    # ── M3U yaz ──────────────────────────────────
    write_m3u(updated_ina, other_channels)

    # ── GitHub'a yükle ───────────────────────────
    if has_changes or not old_ina:
        upload_github()
    else:
        log.info("Değişiklik yok, GitHub atlanıyor")

    # ── Durum kaydet ─────────────────────────────
    state = load_state()
    state["last_run"]      = datetime.now().isoformat()
    state["total_channels"] = len(updated_ina)
    state["raw_url"] = (
        f"https://raw.githubusercontent.com/"
        f"{GITHUB_REPO}/{GITHUB_BRANCH}/{M3U_FILE}"
        if GITHUB_REPO else ""
    )
    save_state(state)

    log.info("\n" + "="*65)
    log.info("✅ Tamamlandı!")
    if state.get("raw_url"):
        log.info(f"📺 IPTV URL: {state['raw_url']}")
    log.info("="*65)


if __name__ == "__main__":
    main()
