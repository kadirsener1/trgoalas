import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import json
import requests
from parser import extract_m3u8

STATE_FILE = "state.json"
M3U_FILE = "playlist.m3u"

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"urls": []}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def fetch_sources(url):
    r = requests.get(url, timeout=10, verify=False)
    return r.text

def update_playlist(new_urls):
    with open(M3U_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # eski linkleri temizle
    lines = [l for l in lines if not l.startswith("http")]

    # yeni linkleri ekle
    for u in new_urls:
        lines.append(u + "\n")

    with open(M3U_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)

def run():
    import json
    with open("config.json") as f:
        config = json.load(f)

    state = load_state()
    old_urls = set(state["urls"])

    all_urls = set()

    for src in config["sources"]:
        html = fetch_sources(src)
        urls = extract_m3u8(html)
        all_urls.update(urls)

    added = list(all_urls - old_urls)

    if added:
        print(f"{len(added)} yeni link bulundu")

        update_playlist(all_urls)
        save_state({"urls": list(all_urls)})
    else:
        print("Değişiklik yok")

if __name__ == "__main__":
    run()
