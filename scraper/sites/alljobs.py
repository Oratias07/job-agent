"""Scraper for AllJobs.co.il — major Israeli job board (Playwright, JS-rendered)."""

import logging
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

BASE_URL = "https://www.alljobs.co.il"
SEARCH_URL = (
    "https://www.alljobs.co.il/SearchResultsGuest.aspx"
    "?FromType=1&type=1&position=0&city=0"
    "&q=%D7%A1%D7%98%D7%95%D7%93%D7%A0%D7%98+%D7%AA%D7%95%D7%9B%D7%A0%D7%94"  # "סטודנט תוכנה"
)

KEYWORDS = ["student", "intern", "internship", "סטודנט", "התמחות", "תכנות", "פיתוח"]


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def scrape() -> list[dict]:
    """Return list of job dicts from AllJobs Israel."""
    jobs: list[dict] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(SEARCH_URL, timeout=60000)
            page.wait_for_timeout(4000)

            # Scroll to load more results
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

            # AllJobs uses .job-content or similar list containers
            cards = page.query_selector_all(
                ".job-content, .content-job, div[class*='job-item'], "
                "article[class*='job'], li[class*='job'], "
                ".jobs-list-item, .single-job"
            )

            if not cards:
                # Broader fallback — grab any element with a job link
                cards = page.query_selector_all("div[id*='job'], div[class*='item']")

            for card in cards:
                try:
                    title_el = card.query_selector(
                        "h2, h3, h4, a[class*='title'], span[class*='title'], "
                        ".job-title, .position-name, a[id*='title']"
                    )
                    if not title_el:
                        continue
                    title_text = title_el.inner_text().strip()
                    if not title_text:
                        continue

                    card_text = card.inner_text().strip()

                    if not _matches_keywords(title_text + " " + card_text):
                        continue

                    link_el = card.query_selector("a[href]")
                    link = link_el.get_attribute("href") if link_el else ""
                    if link and not link.startswith("http"):
                        link = f"{BASE_URL}{link}"

                    # Try to extract company name
                    company_el = card.query_selector(
                        ".company-name, .employer-name, [class*='company'], span[class*='employer']"
                    )
                    company = company_el.inner_text().strip() if company_el else "Unknown (AllJobs)"

                    job_id = f"alljobs-{hash(title_text + link) & 0xFFFFFFFF:08x}"

                    jobs.append({
                        "id": job_id,
                        "title": title_text,
                        "company": company,
                        "url": link or SEARCH_URL,
                        "description": card_text,
                    })
                except Exception:
                    logger.debug("AllJobs: failed to parse card", exc_info=True)

            browser.close()

    except Exception:
        logger.exception("AllJobs: scrape failed")

    logger.info("AllJobs: found %d matching jobs", len(jobs))
    return jobs
