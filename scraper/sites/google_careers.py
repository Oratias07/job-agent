"""Scraper for Google Careers Israel — parses embedded JSON from the search page."""

import hashlib
import json
import logging
import re
import requests

logger = logging.getLogger(__name__)

SEARCH_URL = "https://careers.google.com/jobs/results/"
JOB_BASE_URL = "https://careers.google.com/jobs/results/"

KEYWORDS = ["student", "intern", "internship", "part-time", "part time", "סטודנט"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://careers.google.com/",
}


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def _extract_jobs_from_html(html: str) -> list[dict]:
    """Extract job listings embedded in the page as JSON-LD or React state."""
    jobs = []

    # Try JSON-LD structured data (JobPosting schema)
    ld_blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    for block in ld_blocks:
        try:
            data = json.loads(block.strip())
            if isinstance(data, list):
                jobs.extend(j for j in data if isinstance(j, dict) and j.get("@type") == "JobPosting")
            elif isinstance(data, dict) and data.get("@type") == "JobPosting":
                jobs.append(data)
        except json.JSONDecodeError:
            pass

    return jobs


def _fetch_page(query: str) -> list[dict]:
    params = {
        "distance": "50",
        "hl": "en_US",
        "jlo": "en_US",
        "location": "Israel",
        "q": query,
        "sort_by": "relevance",
    }
    resp = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return _extract_jobs_from_html(resp.text)


def scrape() -> list[dict]:
    """Return list of job dicts from Google Careers Israel."""
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    for query in ["student intern", "intern"]:
        try:
            postings = _fetch_page(query)
        except Exception:
            logger.exception("Google Careers: failed to fetch query '%s'", query)
            continue

        for posting in postings:
            title = posting.get("title", "").strip()
            description = posting.get("description", "").strip()
            apply_url = posting.get("url", "") or posting.get("sameAs", "")

            # Location check
            job_location = posting.get("jobLocation", {})
            if isinstance(job_location, list):
                job_location = job_location[0] if job_location else {}
            address = job_location.get("address", {}) if isinstance(job_location, dict) else {}
            country = address.get("addressCountry", "") if isinstance(address, dict) else ""
            loc_text = (address.get("addressLocality", "") + " " + country).lower()

            if loc_text.strip() and "israel" not in loc_text and "il" != country.lower():
                continue

            if not _matches_keywords(title + " " + description):
                continue

            job_id = f"google-{hashlib.md5((title + apply_url).encode()).hexdigest()[:8]}"
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            jobs.append({
                "id": job_id,
                "title": title,
                "company": "Google",
                "url": apply_url or SEARCH_URL,
                "description": description[:800],
            })

    logger.info("Google Careers: found %d matching jobs", len(jobs))
    return jobs
