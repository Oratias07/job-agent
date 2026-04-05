"""Send email notification with tailored CV and cover letter PDFs."""

import os
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

SENDER = "chamyproject@gmail.com"
RECIPIENT = "atiasor85@gmail.com"


def send_email(new_jobs: list[dict], attachments: list[Path]) -> None:
    """Send a single email listing all new jobs, with PDF attachments."""
    if not new_jobs:
        return

    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not password:
        raise ValueError("GMAIL_APP_PASSWORD environment variable not set")

    logger.info("Attempting login with password length: %d, first 4 chars: %s, last 4 chars: %s",
                len(password), password[:4], password[-4:])
    date_str = datetime.now().strftime("%Y-%m-%d")
    companies = sorted({j["company"] for j in new_jobs})
    subject = f"\U0001f195 [{len(new_jobs)}] New Student Jobs | {', '.join(companies)} | {date_str}"

    # Build body
    body_lines = [f"Found {len(new_jobs)} new student/intern job(s):\n"]
    for i, job in enumerate(new_jobs, 1):
        body_lines.append(f"{i}. **{job['title']}** — {job['company']}")
        body_lines.append(f"   {job['url']}\n")
    body_lines.append(f"\n{len(attachments)} PDF(s) attached (tailored CV + cover letter per job).")

    msg = MIMEMultipart()
    msg["From"] = SENDER
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText("\n".join(body_lines), "plain", "utf-8"))

    for filepath in attachments:
        part = MIMEBase("application", "pdf")
        part.set_payload(filepath.read_bytes())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={filepath.name}")
        msg.attach(part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER, password)
            server.send_message(msg)
        logger.info("Email sent: %s", subject)
    except smtplib.SMTPAuthenticationError as e:
        logger.error("Gmail authentication failed: %s", e)
        logger.error("Sender: %s, Password length: %d", SENDER, len(password))
        raise
