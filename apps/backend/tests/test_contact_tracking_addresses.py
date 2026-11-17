"""
16 November: six chains in the booking database were listed with Sentry's error-reporting key
(3b0f...@o17585.ingest.us.sentry.io), which their websites carry in their code, as their email. A tracking
service's address is never a contact; every real address from that database is still kept.
"""
from app.core.internet.contacts import extract

TRACKING = ["3b0f1428e20e8dbb74f77c6c332a21de@o17585.ingest.us.sentry.io",
            "u002ff7b20c2f87f95d7d60d819766c53e983@o274321.ingest.us.sentry.io",
            "abc@sentry.io", "x@sentry-next.wixpress.com"]
REAL = ["partnerships@starbucks.com", "info@afuri.us", "amicisjk@gmail.com", "press@moes.com",
        "hello@arepaandco.com", "b2bsupport@premierinn.com", "contactcorporate@bcpizza.net"]


def test_a_tracking_services_address_is_never_taken_for_an_email():
    page = "<html><body><p>Debug: %s</p><p>Write to us: %s</p></body></html>" % (
        " ".join(TRACKING), " ".join(REAL))
    found = extract(page, "https://www.example-chain.com/contact")
    emails = [e if isinstance(e, str) else e.get("email") for e in (found.get("emails") or [])]
    assert not any(t in emails for t in TRACKING)
    assert all(r in emails for r in REAL)
