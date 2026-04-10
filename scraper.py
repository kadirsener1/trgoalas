from playwright.sync_api import sync_playwright

MEDIA_EXT = [".m3u8", ".mp4", ".ts"]

def crawl(url):
    found = set()

    def handle_request(req):
        try:
            u = req.url
            if any(ext in u for ext in MEDIA_EXT):
                found.add(u)
        except:
            pass

    def handle_response(res):
        try:
            u = res.url
            if any(ext in u for ext in MEDIA_EXT):
                found.add(u)
        except:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0"
        )

        page = context.new_page()

        page.on("request", handle_request)
        page.on("response", handle_response)

        try:
            page.goto(url, timeout=90000)
            page.wait_for_timeout(12000)

            # JS tetikleme (video geç yüklenirse)
            page.mouse.move(300, 300)
            page.wait_for_timeout(5000)

        except:
            pass

        browser.close()

    return list(found)
