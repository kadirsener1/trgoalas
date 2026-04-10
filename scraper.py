import re
import json
import time
from collections import deque
from playwright.sync_api import sync_playwright

STATE_FILE = "state.json"
M3U_FILE = "playlist.m3u"

MAX_PAGES = 50
DELAY = 1


# ───────── STATE ─────────
def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"visited": [], "queue": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ───────── M3U8 COLLECTOR ─────────
def extract_m3u8(page):
    found = []

    def on_response(resp):
        try:
            if ".m3u8" in resp.url:
                found.append(resp.url)
        except:
            pass

    page.on("response", on_response)

    html = page.content()
    found += re.findall(r'https?://[^\s"\']+\.m3u8[^\s"\']*', html)

    return found[0] if found else None


# ───────── CRAWLER ─────────
def crawl(start_urls):
    state = load_state()
    visited = set(state["visited"])
    queue = deque(state["queue"] or start_urls)

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        while queue and len(visited) < MAX_PAGES:
            url = queue.popleft()

            if url in visited:
                continue

            print(f"[→] Visiting: {url}")
            visited.add(url)

            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                time.sleep(DELAY)

                # m3u8 yakala
                m3u8 = extract_m3u8(page)

                if m3u8:
                    print(f"[✓] M3U8: {m3u8}")
                    results.append((url, m3u8))

                # link keşfi
                links = page.eval_on_selector_all(
                    "a",
                    "els => els.map(e => e.href)"
                )

                for l in links:
                    if l and l.startswith("http") and l not in visited:
                        queue.append(l)

            except Exception as e:
                print(f"[!] Error: {e}")

            # state kaydet
            state["visited"] = list(visited)
            state["queue"] = list(queue)
            save_state(state)

        browser.close()

    return results


# ───────── M3U YAZ ─────────
def save_m3u(data):
    with open(M3U_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n\n")

        for i, (page, m3u8) in enumerate(data):
            f.write(f"#EXTINF:-1,Channel {i}\n")
            f.write(m3u8 + "\n\n")


# ───────── MAIN ─────────
if __name__ == "__main__":

    start_urls = [
        "https://example.com"
    ]

    data = crawl(start_urls)

    save_m3u(data)

    print(f"[✓] DONE: {len(data)} streams")
