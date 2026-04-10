from playwright.sync_api import sync_playwright

def crawl_media(url):
    found = set()

    def handle_response(response):
        try:
            u = response.url
            if ".m3u8" in u:
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
        page.on("response", handle_response)

        try:
            page.goto(url, timeout=90000)
            page.wait_for_timeout(8000)
        except:
            pass

        browser.close()

    return list(found)
