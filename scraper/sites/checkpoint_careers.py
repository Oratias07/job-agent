"""Scraper for Check Point Software Careers Israel — uses their SmartRecruiters API."""

import logging
import requests

logger = logging.getLogger(__name__)

# Check Point uses SmartRecruiters ATS; their company ID is 'CheckPointSoftwareTechnologies'
SMARTRECRUITERS_API = (
    "https://api.smartrecruiters.com/v1/companies/CheckPointSoftwareTechnologies/postings"
)
FALLBACK_URL = "https://www.checkpoint.com/careers/"

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
    """Return list of job dicts from Check Point Careers Israel."""
    jobs: list[dict] = []

    try:
        params = {
            "country": "il",  # Israel country code
            "limit": 100,
        }
        resp = requests.get(SMARTRECRUITERS_API, headers=HEADERS, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.exception("Check Point: SmartRecruiters API failed")
        return jobs

    for posting in data.get("content", []):
        title = posting.get("name", "").strip()
        location_obj = posting.get("location", {})
        country = location_obj.get("country", "") if isinstance(location_obj, dict) else ""
        city = location_obj.get("city", "") if isinstance(location_obj, dict) else ""
        job_id_raw = posting.get("id", "")
        apply_url = f"https://www.smartrecruiters.com/CheckPointSoftwareTechnologies/{job_id_raw}" if job_id_raw else FALLBACK_URL

        description = posting.get("jobAd", {}).get("sections", {})
        desc_text = ""
        if isinstance(description, dict):
            for section in description.values():
                if isinstance(section, dict):
                    desc_text += section.get("text", "") + " "

        full_text = title + " " + desc_text
        if not _matches_keywords(full_text):
            continue

        job_id = f"checkpoint-{job_id_raw}" if job_id_raw else f"checkpoint-{title[:30]}"

        jobs.append({
            "id": job_id,
            "title": title,
            "company": "Check Point",
            "url": apply_url,
            "description": f"{city}, {country}\n{desc_text[:800]}".strip(", \n"),
        })

    logger.info("Check Point Careers: found %d matching jobs", len(jobs))
    return jobs
