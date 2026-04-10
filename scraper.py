from playwright.sync_api import sync_playwright

def crawl_media(url):
    found = set()

    def log_request(request):
        try:
            u = request.url
            if ".m3u8" in u:
                found.add(u)
            if ".ts" in u:
                found.add(u)
        except:
            pass

    def log_response(response):
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

        page.on("request", log_request)
        page.on("response", log_response)

        print("OPEN:", url)

        page.goto(url, timeout=90000)

        # video geç yükleniyor olabilir
        page.wait_for_timeout(15000)

        browser.close()

    return list(found)
