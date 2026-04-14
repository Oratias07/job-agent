"""Scraper for Google Careers Israel — uses the public JSON search API."""

import hashlib
import logging
import requests

logger = logging.getLogger(__name__)

API_URL = "https://careers.google.com/api/v3/search/"
JOB_BASE_URL = "https://careers.google.com/jobs/results/"

KEYWORDS = ["student", "intern", "internship", "part-time", "part time", "סטודנט"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://careers.google.com/",
}


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def _fetch_jobs(query: str) -> list[dict]:
    params = {
        "distance": "50",
        "hl": "en_US",
        "jlo": "en_US",
        "location": "Israel",
        "q": query,
        "sort_by": "relevance",
        "page_size": "20",
    }
    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("jobs", [])


def scrape() -> list[dict]:
    """Return list of job dicts from Google Careers Israel."""
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    for query in ["student intern Israel", "intern Israel"]:
        try:
            postings = _fetch_jobs(query)
        except Exception:
            logger.exception("Google Careers: failed to fetch query '%s'", query)
            continue

        for posting in postings:
            title = posting.get("title", "").strip()
            locations = posting.get("locations", [])
            description = posting.get("description", "").strip()
            apply_url = posting.get("apply_url", "")
            job_id_raw = posting.get("id", "")

            # Only include Israel-located positions
            loc_text = " ".join(locations).lower()
            if "israel" not in loc_text and "tel aviv" not in loc_text and "haifa" not in loc_text:
                continue

            if not _matches_keywords(title + " " + description):
                continue

            if not apply_url and job_id_raw:
                apply_url = f"{JOB_BASE_URL}{job_id_raw}"

            job_id = f"google-{job_id_raw}" if job_id_raw else f"google-{hashlib.md5((title + apply_url).encode()).hexdigest()[:8]}"

            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            jobs.append({
                "id": job_id,
                "title": title,
                "company": "Google",
                "url": apply_url or API_URL,
                "description": f"{', '.join(locations)}\n{description}",
            })

    logger.info("Google Careers: found %d matching jobs", len(jobs))
    return jobs
