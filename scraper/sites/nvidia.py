"""Scraper for NVIDIA Careers — prefers the REST API, falls back to Playwright."""

import logging
import requests
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# NVIDIA's career site exposes a REST API behind the scenes
API_URL = "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"

BROWSE_URL = (
    "https://jobs.nvidia.com/careers"
    "?query=Student&start=0&location=Israel&pid=893391945660"
    "&sort_by=relevance&filter_include_remote=1"
)

KEYWORDS = ["student", "intern", "סטודנט", "התמחות", "internship"]


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def _scrape_api() -> list[dict]:
    """Try NVIDIA's Workday REST API."""
    payload = {
        "appliedFacets": {"locationCountry": ["bc33aa3152ec42d4995f4791a106ed09"]},  # Israel
        "limit": 20,
        "offset": 0,
        "searchText": "Student",
    }
    headers = {"Content-Type": "application/json"}
    resp = requests.post(API_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for posting in data.get("jobPostings", []):
        title = posting.get("title", "")
        bullet_fields = posting.get("bulletFields", [])
        description = " ".join(bullet_fields) + " " + title
        external_path = posting.get("externalPath", "")
        url = f"https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite{external_path}" if external_path else BROWSE_URL

        if not _matches_keywords(title + " " + description):
            continue

        job_id = f"nvidia-{posting.get('bulletFields', [''])[0]}-{hash(title) & 0xFFFFFFFF:08x}"
        if external_path:
            # Use the path slug as a more stable ID
            job_id = f"nvidia-{external_path.strip('/').split('/')[-1]}"

        jobs.append({
            "id": job_id,
            "title": title,
            "company": "NVIDIA",
            "url": url,
            "description": description,
        })
    return jobs


def _scrape_playwright() -> list[dict]:
    """Fallback: render NVIDIA's careers page with Playwright."""
    jobs = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BROWSE_URL, timeout=60000)
        page.wait_for_timeout(5000)

        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)

        cards = page.query_selector_all(
            "[data-automation='job-card'], .job-card, article, "
            "div[class*='job'], li[class*='job'], tr[class*='job']"
        )
        for card in cards:
            try:
                title_el = card.query_selector("h2, h3, h4, a[class*='title'], span[class*='title']")
                if not title_el:
                    continue
                title_text = title_el.inner_text().strip()
                card_text = card.inner_text().strip()

                if not _matches_keywords(title_text + " " + card_text):
                    continue

                link_el = card.query_selector("a[href]")
                link = link_el.get_attribute("href") if link_el else ""
                if link and not link.startswith("http"):
                    link = f"https://jobs.nvidia.com{link}"

                job_id = f"nvidia-{hash(title_text + link) & 0xFFFFFFFF:08x}"
                jobs.append({
                    "id": job_id,
                    "title": title_text,
                    "company": "NVIDIA",
                    "url": link or BROWSE_URL,
                    "description": card_text,
                })
            except Exception:
                logger.debug("Failed to parse a card on NVIDIA", exc_info=True)

        browser.close()
    return jobs


def scrape() -> list[dict]:
    """Return list of job dicts, preferring API over browser scraping."""
    try:
        jobs = _scrape_api()
        logger.info("NVIDIA (API): found %d matching jobs", len(jobs))
        return jobs
    except Exception:
        logger.warning("NVIDIA API failed, falling back to Playwright", exc_info=True)

    try:
        jobs = _scrape_playwright()
        logger.info("NVIDIA (Playwright): found %d matching jobs", len(jobs))
        return jobs
    except Exception:
        logger.exception("NVIDIA Playwright scrape also failed")
        return []
