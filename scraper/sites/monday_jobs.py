"""Scraper for Monday.com Careers Israel — uses Greenhouse ATS public API."""

import logging
import requests

logger = logging.getLogger(__name__)

# Monday.com migrated from Lever to Greenhouse
GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/mondaydotcom/jobs"
FALLBACK_URL = "https://monday.com/jobs"

KEYWORDS = ["student", "intern", "internship", "part-time", "part time",
            "junior", "associate", "סטודנט", "התמחות"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def scrape() -> list[dict]:
    """Return list of job dicts from Monday.com Careers Israel."""
    jobs: list[dict] = []

    try:
        resp = requests.get(
            GREENHOUSE_API, headers=HEADERS, timeout=30, params={"content": "true"}
        )
        resp.raise_for_status()
        postings = resp.json().get("jobs", [])
    except Exception:
        logger.exception("Monday.com: Greenhouse API failed")
        return jobs

    for posting in postings:
        title = posting.get("title", "").strip()
        location_obj = posting.get("location", {})
        location = location_obj.get("name", "") if isinstance(location_obj, dict) else ""
        apply_url = posting.get("absolute_url", "") or posting.get("url", "")
        job_id_raw = str(posting.get("id", ""))
        content = posting.get("content", "") or ""

        loc_lower = location.lower()
        if location and "israel" not in loc_lower and "tel aviv" not in loc_lower and "haifa" not in loc_lower:
            continue

        if not _matches_keywords(title + " " + content):
            continue

        job_id = f"monday-{job_id_raw}" if job_id_raw else f"monday-{title[:30]}"
        jobs.append({
            "id": job_id,
            "title": title,
            "company": "Monday.com",
            "url": apply_url or FALLBACK_URL,
            "description": f"{location}\n{content[:800]}".strip(),
        })

    logger.info("Monday.com Careers: found %d matching jobs", len(jobs))
    return jobs
