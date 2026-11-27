"""Outgoing mail (SMTP) for account messages: sign-up verification, approval notices.

Configuration (server environment only; the password never reaches the browser or the log):
  BBP_SMTP_HOST, BBP_SMTP_PORT (465), BBP_SMTP_SECURITY (ssl | starttls), BBP_SMTP_USER, BBP_SMTP_PASSWORD,
  BBP_MAIL_FROM (default the SMTP user), BBP_MAIL_FROM_NAME.
Without a host, nothing is sent and send() returns False, so callers can say the mail is unavailable.
Tests replace `transport` with a list collector."""
from __future__ import annotations

import email.utils
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger(__name__)
TIMEOUT_S = 20
transport = None          # tests: a list that collects EmailMessage objects instead of SMTP


def configured() -> bool:
    return transport is not None or bool(os.environ.get("BBP_SMTP_HOST"))


def _sender() -> tuple[str, str]:
    addr = os.environ.get("BBP_MAIL_FROM") or os.environ.get("BBP_SMTP_USER") or "noreply@localhost"
    return os.environ.get("BBP_MAIL_FROM_NAME", "KORTEX Permit360"), addr


def build(to: str, subject: str, body: str) -> EmailMessage:
    name, addr = _sender()
    msg = EmailMessage()
    msg["From"] = email.utils.formataddr((name, addr))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=addr.split("@", 1)[-1])
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(body)
    return msg


def send(to: str, subject: str, body: str) -> bool:
    """True when the SMTP server accepted the message. Failures are logged without the password and return False."""
    msg = build(to, subject, body)
    if transport is not None:
        transport.append(msg)
        return True
    host = os.environ.get("BBP_SMTP_HOST")
    if not host:
        return False
    port = int(os.environ.get("BBP_SMTP_PORT") or 465)
    sec = os.environ.get("BBP_SMTP_SECURITY", "ssl")
    ctx = ssl.create_default_context()
    try:
        server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT_S, context=ctx) if sec == "ssl" \
            else smtplib.SMTP(host, port, timeout=TIMEOUT_S)
        try:
            server.ehlo()
            if sec == "starttls":
                server.starttls(context=ctx)
                server.ehlo()
            user = os.environ.get("BBP_SMTP_USER")
            if user:
                server.login(user, os.environ.get("BBP_SMTP_PASSWORD", ""))
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                pass
        return True
    except (OSError, smtplib.SMTPException) as e:
        log.warning("mail to %s not sent: %s", to.split("@")[-1], type(e).__name__)
        return False
