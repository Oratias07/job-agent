"""Send email and Telegram notifications with tailored CV and cover letter PDFs."""

import os
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def send_email(new_jobs: list[dict], attachments: list[Path]) -> None:
    """Send a single email listing all new jobs, with PDF attachments."""
    if not new_jobs:
        return

    sender = os.environ.get("GMAIL_USER", "")
    recipient = os.environ.get("OWNER_EMAIL", "")
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
    msg["From"] = sender
    msg["To"] = recipient
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
            server.login(sender, password)
            server.send_message(msg)
        logger.info("Email sent: %s", subject)
    except smtplib.SMTPAuthenticationError as e:
        logger.error("Gmail authentication failed: %s", e)
        logger.error("Sender: %s, Password length: %d", sender, len(password))
        raise


def send_telegram(new_jobs: list[dict], attachments: list[Path]) -> None:
    """Send Telegram message + PDF attachments for each new job.

    Requires env vars:
      TELEGRAM_BOT_TOKEN — bot token from @BotFather
      TELEGRAM_CHAT_ID   — your personal chat ID (send /start to the bot, then
                           query https://api.telegram.org/bot<TOKEN>/getUpdates)
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return

    def _api(method: str, **kwargs):
        url = TELEGRAM_API.format(token=token, method=method)
        resp = requests.post(url, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp.json()

    # Build summary message
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"🆕 *{len(new_jobs)} new job(s) found* — {date_str}\n"]
    for i, job in enumerate(new_jobs, 1):
        lines.append(
            f"{i}\\. *{_tg_escape(job['title'])}* — {_tg_escape(job['company'])}\n"
            f"   [{_tg_escape(job['url'])}]({job['url']})"
        )
    lines.append(f"\n_{len(attachments)} PDF(s) follow_")
    text = "\n".join(lines)

    try:
        _api("sendMessage", data={"chat_id": chat_id, "text": text, "parse_mode": "MarkdownV2"})
    except Exception:
        logger.exception("Telegram: failed to send summary message")

    # Send each PDF as a document
    for pdf_path in attachments:
        try:
            with pdf_path.open("rb") as f:
                _api(
                    "sendDocument",
                    data={"chat_id": chat_id},
                    files={"document": (pdf_path.name, f, "application/pdf")},
                )
            logger.info("Telegram: sent %s", pdf_path.name)
        except Exception:
            logger.exception("Telegram: failed to send %s", pdf_path.name)


def _tg_escape(text: str) -> str:
    """Escape special chars for Telegram MarkdownV2."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text
