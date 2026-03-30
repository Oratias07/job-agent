"""Scraper for Microsoft Careers global site (JS-rendered, uses Playwright)."""

import logging
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

URL = "https://apply.careers.microsoft.com/careers?domain=microsoft.com"

KEYWORDS = ["student", "intern", "סטודנט", "התמחות", "internship"]


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def scrape() -> list[dict]:
    """Return list of job dicts: {id, title, company, url, description}."""
    jobs = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(URL, timeout=60000)

            # Wait for job cards to render
            page.wait_for_timeout(5000)

            # Try scrolling to load more results
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

            # Extract job cards — Microsoft Careers uses various selectors
            cards = page.query_selector_all(
                "[data-automation='job-card'], "
                ".ms-List-cell, "
                "[role='listitem'], "
                ".job-card, "
                "article[class*='job'], "
                "div[class*='JobCard'], "
                "div[class*='jobCard']"
            )

            for card in cards:
                try:
                    title = card.query_selector(
                        "h2, h3, h4, [data-automation='job-title'], "
                        "a[class*='title'], span[class*='title']"
                    )
                    if not title:
                        continue
                    title_text = title.inner_text().strip()
                    card_text = card.inner_text().strip()

                    if not _matches_keywords(title_text + " " + card_text):
                        continue

                    link_el = card.query_selector("a[href]")
                    link = link_el.get_attribute("href") if link_el else ""
                    if link and not link.startswith("http"):
                        link = f"https://apply.careers.microsoft.com{link}"

                    # Try to extract a job ID from the link or card
                    job_id = f"mscareer-{hash(title_text + link) & 0xFFFFFFFF:08x}"

                    jobs.append({
                        "id": job_id,
                        "title": title_text,
                        "company": "Microsoft",
                        "url": link or URL,
                        "description": card_text,
                    })
                except Exception:
                    logger.debug("Failed to parse a card on Microsoft Careers", exc_info=True)

            browser.close()

    except Exception:
        logger.exception("Failed to scrape Microsoft Careers")

    logger.info("Microsoft Careers: found %d matching jobs", len(jobs))
    return jobs
