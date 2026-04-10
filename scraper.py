import re
import json
import time
import os
import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timezone

BASE_DOMAIN = "inattv"
BASE_TLD = ".xyz"
START_NUMBER = 1289
MAX_SEARCH = 50
M3U_FILE = "playlist.m3u"
STATE_FILE = "state.json"
REQUEST_DELAY = 1

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


# ───────── STATE ─────────
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"last_number": START_NUMBER}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ───────── DOMAIN ─────────
def build_url(num):
    return f"https://{BASE_DOMAIN}{num}{BASE_TLD}/"


def is_alive(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        return r.status_code in (200, 301, 302)
    except:
        return False


def find_domain(last):
    base = build_url(last)
    if is_alive(base):
        return last, base

    for i in range(1, MAX_SEARCH):
        for n in (last + i, last - i):
            if n <= 0:
                continue
            url = build_url(n)
            if is_alive(url):
                return n, url
            time.sleep(1)

    return None, None


# ───────── M3U8 EXTRACT (FIX CORE) ─────────
def extract_m3u8(session, url):
    try:
        r = session.get(url, timeout=12)
        html = r.text

        # 1. direkt m3u8
        links = re.findall(r'https?://[^\s"\']+\.m3u8[^\s"\']*', html)

        # 2. JS fallback
        if not links:
            links = re.findall(r'(https?://.*?\.m3u8.*?)["\']', html)

        # 3. iframe içine gir
        soup = BeautifulSoup(html, "lxml")
        iframe = soup.find("iframe")

        if iframe and iframe.get("src"):
            try:
                r2 = session.get(urljoin(url, iframe["src"]), timeout=12)
                html2 = r2.text
                links += re.findall(r'https?://[^\s"\']+\.m3u8[^\s"\']*', html2)
            except:
                pass

        return links[0] if links else None

    except:
        return None


# ───────── SCRAPER ─────────
def scrape(base_url):
    session = requests.Session()
    session.headers.update(HEADERS)

    r = session.get(base_url, timeout=12)
    soup = BeautifulSoup(r.text, "lxml")

    pages = []

    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, a["href"])
        if "channel.html" in url:
            pages.append(url)

    found = {}

    for page in pages:
        print(f"[→] {page}")

        m3u8 = extract_m3u8(session, page)

        if m3u8:
            name = page.split("id=")[-1]

            found[name] = {
                "name": name,
                "url": m3u8
            }

            print(f"[✓] FOUND: {m3u8}")

        time.sleep(REQUEST_DELAY)

    return list(found.values())


# ───────── M3U WRITE ─────────
def write_m3u(channels):
    with open(M3U_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n\n")

        for ch in channels:
            f.write(f"#EXTINF:-1,{ch['name']}\n")
            f.write(ch["url"] + "\n\n")


# ───────── MAIN ─────────
def main():
    print("START SCRAPER")

    state = load_state()

    num, url = find_domain(state["last_number"])

    if not url:
        print("NO DOMAIN")
        return

    print("[✓] DOMAIN:", url)

    channels = scrape(url)

    if not channels:
        print("NO M3U8 FOUND")
        return

    write_m3u(channels)

    state["last_number"] = num
    save_state(state)

    print("[✓] DONE:", len(channels))


if __name__ == "__main__":
    main()
