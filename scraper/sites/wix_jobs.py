"""Scraper for Wix.com Careers Israel — uses Greenhouse ATS public API."""

import logging
import requests

logger = logging.getLogger(__name__)

# Wix uses Greenhouse ATS; their board slug is 'wix'
GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/wix/jobs"
FALLBACK_URL = "https://www.wix.com/jobs"

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
    """Return list of job dicts from Wix Careers."""
    jobs: list[dict] = []

    try:
        resp = requests.get(GREENHOUSE_API, headers=HEADERS, timeout=30, params={"content": "true"})
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.exception("Wix: Greenhouse API failed")
        return jobs

    for posting in data.get("jobs", []):
        title = posting.get("title", "").strip()
        location_obj = posting.get("location", {})
        location = location_obj.get("name", "") if isinstance(location_obj, dict) else ""
        apply_url = posting.get("absolute_url", "") or posting.get("url", "")
        job_id_raw = str(posting.get("id", ""))
        content = posting.get("content", "") or ""

        # Only Israel positions
        loc_lower = location.lower()
        if location and "israel" not in loc_lower and "tel aviv" not in loc_lower and "haifa" not in loc_lower:
            continue

        full_text = title + " " + content
        if not _matches_keywords(full_text):
            continue

        job_id = f"wix-{job_id_raw}" if job_id_raw else f"wix-{title[:30]}"

        jobs.append({
            "id": job_id,
            "title": title,
            "company": "Wix",
            "url": apply_url or FALLBACK_URL,
            "description": f"{location}\n{content[:800]}".strip(),
        })

    logger.info("Wix Careers: found %d matching jobs", len(jobs))
    return jobs
