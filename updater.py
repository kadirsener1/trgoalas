import json
from scraper import crawl_media

STATE_FILE = "state.json"
M3U_FILE = "playlist.m3u"


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"urls": []}


def save_state(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def update_m3u(urls):
    with open(M3U_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # sadece link satırlarını temizle
    lines = [l for l in lines if not l.startswith("http")]

    for u in urls:
        lines.append(u + "\n")

    with open(M3U_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)


def run():

    sources = [
        "https://inattv1289.xyz"
    ]

    state = load_state()
    old_urls = set(state["urls"])
    new_urls = set()

    for s in sources:
        print("Crawling:", s)
        results = crawl_media(s)
        new_urls.update(results)

    added = new_urls - old_urls

    if added:
        print("Yeni linkler:", len(added))
        update_m3u(new_urls)
        save_state({"urls": list(new_urls)})
    else:
        print("Değişiklik yok")


if __name__ == "__main__":
    run()
