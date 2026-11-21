"""Telegram / email notifications and message formatting."""
import os
import smtplib
import sys
from email.message import EmailMessage

from sources.common import http_json


VERDICT_ICON = {"fit": "OK fits", "stretch": "STRETCH", "unknown": "exp not stated"}


def format_message(jobs, cfg):
    order = {"fit": 0, "unknown": 1, "stretch": 2}
    jobs = sorted(jobs, key=lambda j: (j["loc_rank"], order.get(j["exp_label"], 3), j["company"]))
    lines = [f"{len(jobs)} new job(s) (your exp: {cfg['my_years']:g} yrs):", ""]
    for j in jobs:
        lines.append(f"[{j['loc_label']}] {j['company']}: {j['title']}")
        lines.append(f"  Exp: {j['exp_text']} -> {VERDICT_ICON.get(j['exp_label'], j['exp_label'])}")
        lines.append(f"  {j['url']}")
        lines.append("")
    return "\n".join(lines)


def chunk(text, size=3800):
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > size:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts


def send_telegram(text):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return False
    for part in chunk(text):
        http_json(f"https://api.telegram.org/bot{tok}/sendMessage",
                  {"chat_id": chat, "text": part, "disable_web_page_preview": True})
    return True


def send_email(subject, text):
    host, to = os.getenv("SMTP_HOST"), os.getenv("EMAIL_TO")
    user, pw = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    if not (host and to and user and pw):
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(text)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT") or "587")) as s:
        s.starttls()
        s.login(user, pw)
        s.send_message(msg)
    return True


def notify(text, subject="Job watcher"):
    """Send via Telegram/email. Returns True if delivered (or no channel is configured, stdout only)."""
    configured = bool((os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
                      or (os.getenv("SMTP_HOST") and os.getenv("EMAIL_TO")))
    sent = False
    try:
        sent = send_telegram(text) or sent
    except Exception as e:
        print(f"[warn] telegram failed: {e}", file=sys.stderr)
    try:
        sent = send_email(subject, text) or sent
    except Exception as e:
        print(f"[warn] email failed: {e}", file=sys.stderr)
    if not sent:
        print(text)
    return sent or not configured
