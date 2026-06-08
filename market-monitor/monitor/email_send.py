"""Send a multipart (text + html) email via SMTP — Gmail by default.

Gmail requires an *App Password* (Account → Security → App passwords, with
2-Step Verification enabled); a normal account password will be rejected.
"""

from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(
    subject: str,
    html_body: str,
    text_body: str,
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    sender: str,
    recipient: str,
    timeout: int = 20,
) -> bool:
    """Send the email. Returns True on success, False (and prints) on failure."""
    if not (user and password and recipient):
        print("[email] not configured (need EMAIL_USER, EMAIL_PASSWORD, EMAIL_TO) — skipping")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender or user
    msg["To"] = recipient
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=timeout) as s:
                s.login(user, password)
                s.sendmail(msg["From"], [recipient], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as s:
                s.ehlo()
                s.starttls(context=ctx)
                s.ehlo()
                s.login(user, password)
                s.sendmail(msg["From"], [recipient], msg.as_string())
        print(f"[email] ✅ sent to {recipient}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[email] ❌ send failed: {e}")
        return False
