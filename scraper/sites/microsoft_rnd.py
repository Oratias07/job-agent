"""Scraper for Microsoft R&D Israel jobs page (static HTML)."""

import hashlib
import logging
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

URL = "https://www.microsoftrnd.co.il/jobs"

KEYWORDS = ["student", "intern", "סטודנט", "התמחות", "internship"]


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def _stable_id(url: str, title: str) -> str:
    """Use JobSeqNo from URL as canonical ID; fall back to hash of title+url."""
    qs = parse_qs(urlparse(url).query)
    seq = qs.get("JobSeqNo", [None])[0]
    if seq:
        return f"msrnd-{seq}"
    return f"msrnd-{hashlib.md5((title + url).encode()).hexdigest()[:8]}"


def scrape() -> list[dict]:
    """Return list of job dicts: {id, title, company, url, description}."""
    jobs = []
    seen_urls: set[str] = set()

    try:
        resp = requests.get(URL, timeout=30)
        resp.raise_for_status()
    except Exception:
        logger.exception("Failed to fetch %s", URL)
        return jobs

    soup = BeautifulSoup(resp.text, "html.parser")

    # Primary path: structured job card selectors
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

        if link in seen_urls:
            continue
        seen_urls.add(link)

        jobs.append({
            "id": _stable_id(link, title),
            "title": title,
            "company": "Microsoft R&D Israel",
            "url": link or URL,
            "description": description,
        })

    # Fallback: scan all links with keyword-matching href
    if not jobs:
        for a in soup.find_all("a", href=True):
            link = a["href"]
            if not link.startswith("http"):
                link = f"https://www.microsoftrnd.co.il{link}"

            # Only follow links that look like job detail pages
            if "JobDetails" not in link and "JobSeqNo" not in link:
                continue

            if link in seen_urls:
                continue

            text = a.get_text(strip=True)
            parent_text = a.parent.get_text(strip=True) if a.parent else text
            if not _matches_keywords(text + " " + parent_text):
                continue

            seen_urls.add(link)
            jobs.append({
                "id": _stable_id(link, text),
                "title": text,
                "company": "Microsoft R&D Israel",
                "url": link,
                "description": parent_text,
            })

    logger.info("Microsoft R&D Israel: found %d matching jobs", len(jobs))
    return jobs
