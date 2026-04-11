"""Scraper for HiremeTech.com — tech-focused job board (Playwright, JS-rendered)."""

import hashlib
import logging
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hiremetech.com"
SEARCH_URL = "https://www.hiremetech.com/jobs"

KEYWORDS = ["student", "intern", "internship", "junior", "entry", "graduate",
            "סטודנט", "התמחות", "ג'וניור", "פיתוח"]


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def scrape() -> list[dict]:
    """Return list of job dicts from HiremeTech."""
    jobs: list[dict] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Try search with student/intern keywords
            for search_term in ["student", "intern", "junior"]:
                try:
                    url = f"{SEARCH_URL}?q={search_term}"
                    page.goto(url, timeout=60000)
                    page.wait_for_timeout(4000)

                    for _ in range(3):
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(1500)

                    cards = page.query_selector_all(
                        ".job-card, .job-listing, .job-item, .position-card, "
                        "article[class*='job'], div[class*='JobCard'], "
                        "div[class*='job-result'], li[class*='job'], "
                        "[data-testid*='job'], [data-job-id]"
                    )

                    # Broad fallback — any clickable job-looking element
                    if not cards:
                        cards = page.query_selector_all(
                            "main article, main li, .results-list > div, "
                            ".jobs-container > div"
                        )

                    for card in cards:
                        try:
                            title_el = card.query_selector(
                                "h1, h2, h3, h4, "
                                "[class*='title'], [class*='Title'], "
                                "[data-testid*='title'], a[class*='job']"
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
                                "[class*='company'], [class*='Company'], "
                                "[class*='employer'], span[class*='org']"
                            )
                            company = company_el.inner_text().strip() if company_el else "Unknown (HiremeTech)"

                            job_id = f"hiemetech-{hashlib.md5((title_text + link).encode()).hexdigest()[:8]}"

                            # Avoid duplicates within this scraper
                            if not any(j["id"] == job_id for j in jobs):
                                jobs.append({
                                    "id": job_id,
                                    "title": title_text,
                                    "company": company,
                                    "url": link or SEARCH_URL,
                                    "description": card_text,
                                })
                        except Exception:
                            logger.debug("HiremeTech: failed to parse card", exc_info=True)

                except Exception:
                    logger.debug("HiremeTech: failed to search for '%s'", search_term, exc_info=True)

            browser.close()

    except Exception:
        logger.exception("HiremeTech: scrape failed")

    logger.info("HiremeTech: found %d matching jobs", len(jobs))
    return jobs
