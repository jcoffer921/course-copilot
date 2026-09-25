from agent.services import email_domain


def test_personal_sender_is_allowed_for_pilot_but_warned(settings):
    settings.DEFAULT_FROM_EMAIL = "OnTrack <pilot@gmail.com>"
    assert email_domain.check_sender_domain()[0]["status"] == "warning"


def test_owned_sender_checks_spf_dkim_and_dmarc(settings, monkeypatch):
    settings.DEFAULT_FROM_EMAIL = "OnTrack <reminders@ontrack.example>"
    monkeypatch.setenv("ONTRACK_DKIM_SELECTOR", "pilot")
    records = {
        "ontrack.example": ["v=spf1 include:_spf.example ~all"],
        "pilot._domainkey.ontrack.example": ["v=DKIM1; p=abc"],
        "_dmarc.ontrack.example": ["v=DMARC1; p=quarantine"],
    }
    monkeypatch.setattr(email_domain, "_txt", lambda name: records.get(name, []))
    assert [row["status"] for row in email_domain.check_sender_domain()] == ["ok", "ok", "ok"]
