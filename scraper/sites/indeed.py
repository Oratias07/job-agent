"""Scraper for Indeed Israel — uses public RSS feed (no auth, no JS required)."""

import logging
import re
import xml.etree.ElementTree as ET

import requests

logger = logging.getLogger(__name__)

RSS_URLS = [
    "https://il.indeed.com/rss?q=software+student&l=Israel&lang=en",
    "https://il.indeed.com/rss?q=software+intern&l=Israel&lang=en",
    "https://il.indeed.com/rss?q=%D7%A1%D7%98%D7%95%D7%93%D7%A0%D7%98+%D7%AA%D7%95%D7%9B%D7%A0%D7%94&l=%D7%99%D7%A9%D7%A8%D7%90%D7%9C",  # Hebrew: student software
]

KEYWORDS = ["student", "intern", "internship", "סטודנט", "התמחות"]

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


def _parse_rss(xml_text: str) -> list[dict]:
    jobs = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.warning("Indeed: failed to parse RSS XML")
        return jobs

    ns = {"dc": "http://purl.org/dc/elements/1.1/"}
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")

        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        link = link_el.text.strip() if link_el is not None and link_el.text else ""
        raw_desc = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

        # Strip HTML tags from description
        description = re.sub(r"<[^>]+>", " ", raw_desc)
        description = re.sub(r"\s+", " ", description).strip()

        # Extract company name from title ("Job Title - Company - Location" is Indeed's format)
        company = "Indeed"
        parts = title.split(" - ")
        if len(parts) >= 2:
            company = parts[-2].strip() if len(parts) >= 3 else parts[1].strip()
            title = parts[0].strip()

        if not _matches_keywords(title + " " + description):
            continue

        # Use a hash of the link (Indeed job IDs are embedded in the URL)
        m = re.search(r"jk=([a-f0-9]+)", link)
        job_id = f"indeed-{m.group(1)}" if m else f"indeed-{hash(title + link) & 0xFFFFFFFF:08x}"

        jobs.append({
            "id": job_id,
            "title": title,
            "company": company,
            "url": link,
            "description": description,
        })
    return jobs


def scrape() -> list[dict]:
    """Return list of job dicts from Indeed Israel RSS feeds."""
    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    for url in RSS_URLS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            jobs = _parse_rss(resp.text)
            for job in jobs:
                if job["id"] not in seen_ids:
                    seen_ids.add(job["id"])
                    all_jobs.append(job)
        except Exception:
            logger.exception("Indeed: failed to fetch %s", url)

    logger.info("Indeed Israel: found %d matching jobs", len(all_jobs))
    return all_jobs
