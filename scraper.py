import re
import json
import time
import os
import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timezone

# ─── YAPILANDIRMA ────────────────────────────────────────────────
BASE_DOMAIN   = "inattv"          # domain ön eki
BASE_TLD      = ".xyz"             # domain son eki
START_NUMBER  = 1289              # başlangıç sayısı
MAX_SEARCH    = 50               # kaç sayı ileriye kadar aransın
M3U_FILE      = "playlist.m3u"
STATE_FILE    = "state.json"      # son aktif domain numarasını saklar
REQUEST_DELAY = 2                # istekler arası bekleme (saniye)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# VLC opts referer şablonu — {domain} yer tutucu olarak kullanılır
VLC_REFERER_TPL = "https://{domain}/"


# ─── STATE YÖNETIMI ──────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    raise ValueError("Boş dosya")
                return json.loads(content)
        except Exception as e:
            print(f"[!] state.json bozuk veya boş, sıfırlanıyor: {e}")
    
    return {
        "last_number": START_NUMBER,
        "last_domain": "",
        "last_updated": ""
    }
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_number": START_NUMBER, "last_domain": "", "last_updated": ""}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ─── DOMAİN BULMA ────────────────────────────────────────────────
def build_url(number: int) -> str:
    return f"https://{BASE_DOMAIN}{number}{BASE_TLD}/"

def is_site_alive(url: str) -> bool:
    try:
        r = requests.get(url, headers=HEADERS, timeout=8, allow_redirects=True)
        # 200 veya içerik varsa aktif say
        return r.status_code in (200, 301, 302) and len(r.text) > 500
    except Exception:
        return False

def find_active_domain(last_number: int) -> tuple:
    """Son bilinen numaradan başlayarak aktif domaini bul."""
    print(f"[*] Domain tarama başlıyor: {BASE_DOMAIN}{last_number}{BASE_TLD} ...")
    
    # Önce son bilinen URL'yi dene
    current_url = build_url(last_number)
    if is_site_alive(current_url):
        print(f"[✓] Mevcut domain hâlâ aktif: {current_url}")
        return last_number, current_url
    
    # Yeni numaraları tara (hem ileri hem geri)
    candidates = []
    for i in range(1, MAX_SEARCH + 1):
        candidates.append(last_number + i)
        if last_number - i > 0:
            candidates.append(last_number - i)
    
    for num in candidates:
        url = build_url(num)
        print(f"  [-] Deneniyor: {url}")
        if is_site_alive(url):
            print(f"[✓] Yeni aktif domain bulundu: {url}")
            return num, url
        time.sleep(REQUEST_DELAY)
    
    print("[✗] Aktif domain bulunamadı!")
    return None, None


# ─── M3U8 SCRAPING ───────────────────────────────────────────────
def scrape_m3u8_links(base_url: str) -> list:
    """Siteden ve alt sayfalardan m3u8 linklerini topla."""
    found = {}  # {kanal_adı: {"url": ..., "logo": ...}}
    session = requests.Session()
    session.headers.update(HEADERS)
    session.headers["Referer"] = base_url

    pages_to_scrape = [base_url]
    scraped = set()

    M3U8_PATTERN = re.compile(
        r'https?://[^\s\'"<>,;{}()\[\]]+\.m3u8[^\s\'"<>,;{}()\[\]]*',
        re.IGNORECASE
    )

    for page_url in pages_to_scrape:
        if page_url in scraped:
            continue
        scraped.add(page_url)

        try:
            print(f"  [→] Scraping: {page_url}")
            r = session.get(page_url, timeout=12)
            html = r.text
        except Exception as e:
            print(f"  [!] Hata: {e}")
            continue

        # Ham HTML'den m3u8 URL'lerini çek
        raw_links = M3U8_PATTERN.findall(html)
        
        # JS değişkenlerinden de çek (source, file, src, stream vs.)
        js_patterns = [
            re.compile(r'(?:source|file|src|stream|url|hls_src)\s*[=:]\s*["\']([^"\']+\.m3u8[^"\']*)["\']', re.I),
            re.compile(r'(?:source|file|src|stream|url|hls_src)\s*[=:]\s*`([^`]+\.m3u8[^`]*)`', re.I),
        ]
        for pat in js_patterns:
            raw_links.extend(pat.findall(html))

        # BeautifulSoup ile iframe / script / video src tara
        soup = BeautifulSoup(html, "lxml")
        
        # Kanal linkleri için a[href] tara
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href and not href.startswith("#") and not href.startswith("javascript"):
                full_href = urljoin(base_url, href)
                # Sadece aynı domain alt sayfaları
                if BASE_DOMAIN in full_href and full_href not in scraped:
                    if len(pages_to_scrape) < 30:  # max 30 sayfa
                        pages_to_scrape.append(full_href)

        # Bulunan m3u8 linklerini işle
        for link in set(raw_links):
            link = link.strip().rstrip(",;'\"")
            if not link.startswith("http"):
                continue
            
            # Kanal adını bulmaya çalış
            channel_name = extract_channel_name(soup, link, html)
            logo = extract_logo(soup, channel_name)
            
            key = channel_name.lower()
            if key not in found:
                found[key] = {"name": channel_name, "url": link, "logo": logo}
                print(f"  [+] Bulundu: {channel_name} → {link[:60]}...")
        
        time.sleep(REQUEST_DELAY)

    return list(found.values())


def extract_channel_name(soup, link: str, html: str) -> str:
    """URL veya HTML'den kanal adı çıkarmaya çalış."""
    # URL'den kanal adı çıkar
    url_parts = link.split("/")
    for part in reversed(url_parts):
        part = part.replace(".m3u8", "").replace("_", " ").replace("-", " ")
        if 2 < len(part) < 40 and not part.startswith("?"):
            return part.strip().title()
    
    # Bein Sports pattern kontrolü
    bein_match = re.search(r'bein[\s_-]?sports?[\s_-]?(\d+)?', link, re.I)
    if bein_match:
        num = bein_match.group(1) or ""
        return f"beIN Sports {num}".strip()
    
    return "İnat TV Kanal"

def extract_logo(soup, channel_name: str) -> str:
    """Kanal adına göre logo bul."""
    name_lower = channel_name.lower()
    LOGOS = {
        "bein sports 1": "https://i.imgur.com/YCHuEaE.png",
        "bein sports 2": "https://i.imgur.com/8MiWQaP.png",
        "bein sports 3": "https://i.imgur.com/mPlqKqT.png",
        "bein sports 4": "https://i.imgur.com/BKNS1Pu.png",
        "bein sports haber": "https://i.imgur.com/WtpKBaI.png",
        "bein connect": "https://i.imgur.com/JJkBcLy.png",
        "tabii": "https://i.imgur.com/GRBkWVN.png",
        "exxen": "https://i.imgur.com/3dPoZBX.png",
    }
    for k, v in LOGOS.items():
        if k in name_lower:
            return v
    return ""


# ─── M3U DOSYASI GÜNCELLEME ──────────────────────────────────────
def build_m3u_entry(ch: dict, domain: str) -> str:
    """Tek bir kanal için VLC destekli M3U girişi oluştur."""
    referer = VLC_REFERER_TPL.format(domain=domain)
    logo_part = f' tvg-logo="{ch["logo"]}"' if ch.get("logo") else ""
    lines = [
        f'#EXTINF:-1 tvg-name="{ch["name"]}"{logo_part} group-title="İnat TV",{ch["name"]}',
        f'#EXTVLCOPT:http-referrer={referer}',
        f'#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        f'#KODIPROP:inputstream.adaptive.manifest_type=hls',
        f'#KODIPROP:inputstream.adaptive.license_type=org.w3.clearkey',
        ch["url"],
        ""
    ]
    return "\n".join(lines)

def is_inat_entry(block: str, old_domains: list) -> bool:
    """Bu M3U bloğu inat TV'ye ait mi?"""
    lower = block.lower()
    if "İnat tv".lower() in lower:
        return True
    for d in old_domains:
        if d.lower() in lower:
            return True
    return False

def update_m3u_file(channels: list, domain: str, domain_num: int):
    """M3U dosyasını güncelle — sadece inat TV bloklarını değiştir."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    full_domain = f"{BASE_DOMAIN}{domain_num}{BASE_TLD}"

    # Eski bloğun domain listesi (hem 1289 hem de diğerleri)
    old_domains = [f"{BASE_DOMAIN}{n}{BASE_TLD}" for n in range(1200, 1400)]

    # Yeni inat TV bloğunu oluştur
    new_inat_block = \
        f"# === İnat TV Kanalları ({full_domain}) - Son Güncelleme: {now} ===\n"
    for ch in channels:
        new_inat_block += build_m3u_entry(ch, full_domain)
    new_inat_block += "# === İnat TV Sonu ===\n"

    # Mevcut M3U'yu oku
    if os.path.exists(M3U_FILE):
        with open(M3U_FILE, "r", encoding="utf-8") as f:
            existing = f.read()
    else:
        existing = "#EXTM3U x-tvg-url=\"\"\n"

    # Dosya başlığı + diğer satırları ayır
    lines = existing.split("\n")
    header = lines[0] if lines[0].startswith("#EXTM3U") else "#EXTM3U"

    # İnat TV bloklarını tespit et ve çıkar (diğerlerini koru)
    entries = []
    current_block = []
    in_inat_section = False
    other_lines = []

    for line in lines[1:]:
        if "İnat TV Kanalları" in line or "inat tv" in line.lower():
            in_inat_section = True
        if "İnat TV Sonu" in line:
            in_inat_section = False
            continue
        if not in_inat_section:
            other_lines.append(line)

    # Ayrıca eski inat domain URL'lerini olan #EXTINF bloklarını temizle
    cleaned_others = []
    skip_next = False
    i = 0
    while i < len(other_lines):
        line = other_lines[i]
        if line.startswith("#EXTINF"):
            # Sonraki satır(lar)da URL var mı kontrol et
            block_lines = [line]
            j = i + 1
            while j < len(other_lines) and not other_lines[j].startswith("#EXTINF"):
                block_lines.append(other_lines[j])
                j += 1
            block_text = "\n".join(block_lines)
            if is_inat_entry(block_text, old_domains):
                i = j  # Bu bloğu atla
                continue
            else:
                cleaned_others.extend(block_lines)
                i = j
        else:
            cleaned_others.append(line)
            i += 1

    # Yeni dosyayı oluştur
    other_content = "\n".join(cleaned_others).strip()
    final_content = header + "\n\n"
    if other_content:
        final_content += other_content + "\n\n"
    final_content += new_inat_block

    with open(M3U_FILE, "w", encoding="utf-8") as f:
        f.write(final_content)
    
    print(f"\n[✓] M3U dosyası güncellendi: {M3U_FILE}")
    print(f"[✓] Toplam İnat TV kanalı: {len(channels)}")


# ─── ANA AKIŞ ────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("  İnat TV M3U8 Scraper & Güncelleyici")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 55)

    # 1. State yükle
    state = load_state()
    last_num = state.get("last_number", START_NUMBER)

    # 2. Aktif domaini bul
    domain_num, active_url = find_active_domain(last_num)
    if not active_url:
        print("[✗] Hiçbir aktif domain bulunamadı. Çıkılıyor.")
        sys.exit(1)

    # 3. M3U8 linklerini scrape et
    print(f"\n[*] M3U8 linkleri taranıyor: {active_url}")
    channels = scrape_m3u8_links(active_url)

    if not channels:
        print("[!] Hiç m3u8 linki bulunamadı. M3U güncellenmedi.")
        return

    # 4. M3U dosyasını güncelle
    update_m3u_file(channels, active_url, domain_num)

    # 5. State'i güncelle
    state["last_number"] = domain_num
    state["last_domain"] = f"{BASE_DOMAIN}{domain_num}{BASE_TLD}"
    state["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    save_state(state)
    
    print(f"[✓] State kaydedildi: {state}")
    print("[✓] Tamamlandı!")

if __name__ == "__main__":
    main()
