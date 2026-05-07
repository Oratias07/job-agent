"""Scraper for Wix.com Careers Israel — uses Greenhouse ATS public API."""

import logging
import requests

logger = logging.getLogger(__name__)

# Wix may use different Greenhouse board slugs — try in order
GREENHOUSE_SLUGS = ["wixcom", "wix", "wix-com"]
GREENHOUSE_BASE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
FALLBACK_URL = "https://www.wix.com/jobs/locations/israel"

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


def _fetch_greenhouse(slug: str) -> list[dict] | None:
    """Try a Greenhouse board slug, return postings list or None on failure."""
    url = GREENHOUSE_BASE.format(slug=slug)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, params={"content": "true"})
        resp.raise_for_status()
        return resp.json().get("jobs", [])
    except Exception:
        return None


def scrape() -> list[dict]:
    """Return list of job dicts from Wix Careers."""
    postings = None
    for slug in GREENHOUSE_SLUGS:
        postings = _fetch_greenhouse(slug)
        if postings is not None:
            logger.info("Wix: using Greenhouse slug '%s'", slug)
            break

    if postings is None:
        logger.error("Wix: all Greenhouse slugs failed — %s", GREENHOUSE_SLUGS)
        return []

    jobs: list[dict] = []
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
