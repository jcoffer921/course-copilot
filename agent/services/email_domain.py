import os
from email.utils import parseaddr

import dns.resolver
from django.conf import settings

PERSONAL_PROVIDERS = {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com"}


def _txt(name):
    try:
        return ["".join(part.decode() for part in answer.strings) for answer in dns.resolver.resolve(name, "TXT")]
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
        return []


def check_sender_domain():
    _, address = parseaddr(settings.DEFAULT_FROM_EMAIL)
    domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    if not domain:
        return [{"name": "sender_address", "status": "error", "detail": "DEFAULT_FROM_EMAIL is invalid."}]
    if domain in PERSONAL_PROVIDERS:
        return [{
            "name": "branded_sender_domain", "status": "warning",
            "detail": f"{domain} can send pilot mail, but use an owned domain for branded production delivery.",
        }]
    selector = os.environ.get("ONTRACK_DKIM_SELECTOR", "google").strip()
    spf = any(record.lower().startswith("v=spf1") for record in _txt(domain))
    dmarc = any(record.lower().startswith("v=dmarc1") for record in _txt(f"_dmarc.{domain}"))
    dkim = bool(selector and _txt(f"{selector}._domainkey.{domain}"))
    return [
        {"name": "spf", "status": "ok" if spf else "error", "detail": "SPF record found." if spf else f"Publish an SPF TXT record for {domain}."},
        {"name": "dkim", "status": "ok" if dkim else "error", "detail": "DKIM record found." if dkim else f"Publish the {selector} DKIM TXT record for {domain}."},
        {"name": "dmarc", "status": "ok" if dmarc else "error", "detail": "DMARC record found." if dmarc else f"Publish a DMARC TXT record at _dmarc.{domain}."},
    ]
