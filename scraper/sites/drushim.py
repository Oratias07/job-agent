"""Scraper for Drushim.co.il — Israeli job board (Playwright, JS-rendered)."""

import logging
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

BASE_URL = "https://www.drushim.co.il"
# Search for student/intern software jobs
SEARCH_URL = (
    "https://www.drushim.co.il/jobs/cat12/"  # category 12 = hi-tech / software
    "?q=%D7%A1%D7%98%D7%95%D7%93%D7%A0%D7%98"  # q=סטודנט
)

KEYWORDS = ["student", "intern", "internship", "סטודנט", "התמחות", "תכנות", "פיתוח"]


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def scrape() -> list[dict]:
    """Return list of job dicts from Drushim Israel."""
    jobs: list[dict] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(SEARCH_URL, timeout=60000)
            page.wait_for_timeout(4000)

            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

            # Drushim uses .job-item or li-based job lists
            cards = page.query_selector_all(
                ".job-item, .job_item, li[class*='job'], "
                "div[class*='job-box'], article[class*='job'], "
                ".vacancy-item, .position-item"
            )

            if not cards:
                cards = page.query_selector_all("div[class*='item'], li[class*='result']")

            for card in cards:
                try:
                    title_el = card.query_selector(
                        "h2, h3, h4, a[class*='title'], .job-title, .position-title, "
                        "span[class*='title'], a[class*='job']"
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

                    company_el = card.query_selector(
                        ".company-name, .employer, [class*='company'], "
                        "span[class*='employer'], a[class*='company']"
                    )
                    company = company_el.inner_text().strip() if company_el else "Unknown (Drushim)"

                    job_id = f"drushim-{hash(title_text + link) & 0xFFFFFFFF:08x}"

                    jobs.append({
                        "id": job_id,
                        "title": title_text,
                        "company": company,
                        "url": link or SEARCH_URL,
                        "description": card_text,
                    })
                except Exception:
                    logger.debug("Drushim: failed to parse card", exc_info=True)

            browser.close()

    except Exception:
        logger.exception("Drushim: scrape failed")

    logger.info("Drushim: found %d matching jobs", len(jobs))
    return jobs
