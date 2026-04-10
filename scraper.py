from playwright.sync_api import sync_playwright

MEDIA_EXTENSIONS = [".m3u8", ".mp4", ".ts"]

def crawl_media(url):
    found = set()

    def on_response(response):
        try:
            rurl = response.url
            if any(ext in rurl for ext in MEDIA_EXTENSIONS):
                found.add(rurl)
        except:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        page = context.new_page()
        page.on("response", on_response)

        page.goto(url, wait_until="networkidle", timeout=60000)

        # ekstra JS tetikleme
        page.wait_for_timeout(5000)

        browser.close()

    return list(found)
