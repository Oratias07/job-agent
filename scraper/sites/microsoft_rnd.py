"""Scraper for Microsoft R&D Israel jobs page (static HTML)."""

import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

URL = "https://www.microsoftrnd.co.il/jobs"

KEYWORDS = ["student", "intern", "סטודנט", "התמחות", "internship"]


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def scrape() -> list[dict]:
    """Return list of job dicts: {id, title, company, url, description}."""
    jobs = []
    try:
        resp = requests.get(URL, timeout=30)
        resp.raise_for_status()
    except Exception:
        logger.exception("Failed to fetch %s", URL)
        return jobs

    soup = BeautifulSoup(resp.text, "html.parser")

    # Microsoft R&D Israel uses various layouts — try common patterns
    # Look for job listing containers
    for card in soup.select("[data-testid='job-card'], .job-card, .career-item, .position-item, li.job, article"):
        title_el = card.select_one("h2, h3, h4, .job-title, .position-title, a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        description = card.get_text(strip=True)

        if not _matches_keywords(title + " " + description):
            continue

        link = title_el.get("href") or ""
        if link and not link.startswith("http"):
            link = f"https://www.microsoftrnd.co.il{link}"

        job_id = f"msrnd-{hash(title + link) & 0xFFFFFFFF:08x}"

        jobs.append({
            "id": job_id,
            "title": title,
            "company": "Microsoft R&D Israel",
            "url": link or URL,
            "description": description,
        })

    # Fallback: if no structured cards found, scan all links
    if not jobs:
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            parent_text = a.parent.get_text(strip=True) if a.parent else text
            if _matches_keywords(text + " " + parent_text):
                link = a["href"]
                if not link.startswith("http"):
                    link = f"https://www.microsoftrnd.co.il{link}"
                job_id = f"msrnd-{hash(text + link) & 0xFFFFFFFF:08x}"
                jobs.append({
                    "id": job_id,
                    "title": text,
                    "company": "Microsoft R&D Israel",
                    "url": link,
                    "description": parent_text,
                })

    logger.info("Microsoft R&D Israel: found %d matching jobs", len(jobs))
    return jobs
