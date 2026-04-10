import json
from scraper import crawl

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


def write_m3u(urls):
    with open(M3U_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for u in urls:
            f.write(u + "\n")


def run():

    # GENEL KAYNAK LİSTESİ (izinli / kendi siten olmalı)
    sources = [
        "https://example.com"
    ]

    state = load_state()

    old = set(state["urls"])
    new = set()

    for s in sources:
        print("Crawling:", s)
        results = crawl(s)
        new.update(results)

    added = new - old

    print("Toplam:", len(new))
    print("Yeni:", len(added))

    if added:
        write_m3u(new)
        save_state({"urls": list(new)})
        print("M3U güncellendi")
    else:
        print("Değişiklik yok")


if __name__ == "__main__":
    run()
