from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from agent.models import GoogleCalendarConnection
from agent.services import calendar_sync, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def user_with_valid_token(db):
    user = User.objects.create_user(username="sub-123", email="jordan@example.com")
    GoogleCalendarConnection.objects.create(
        user=user,
        access_token="valid-access-token", refresh_token="refresh-token-value",
        token_expiry=timezone.now() + timedelta(hours=1),
    )
    return user


def _mock_calendar_build(event_id="event-abc"):
    """Mocks googleapiclient.discovery.build("calendar", "v3", ...) down to
    .events().insert(...).execute()."""
    mock_service = MagicMock()
    mock_service.events.return_value.insert.return_value.execute.return_value = {"id": event_id}
    return mock_service


@pytest.mark.django_db
def test_add_deadline_to_calendar_creates_event_and_records_it(isolated_courses_dir, user_with_valid_token):
    with patch("agent.services.calendar_sync.build", return_value=_mock_calendar_build("event-abc")) as build:
        result = calendar_sync.add_deadline_to_calendar(
            user_with_valid_token, "cs101", "2026-09-01", "Midterm", "exam",
        )

    assert result == {"google_event_id": "event-abc"}
    build.assert_called_once()
    records = storage.read_calendar_sync("cs101", user=user_with_valid_token)
    assert len(records) == 1
    assert records[0]["date"] == "2026-09-01"
    assert records[0]["title"] == "Midterm"
    assert records[0]["google_event_id"] == "event-abc"


@pytest.mark.django_db
def test_add_deadline_to_calendar_sends_an_all_day_event_with_exclusive_end_date(isolated_courses_dir, user_with_valid_token):
    mock_service = _mock_calendar_build()
    with patch("agent.services.calendar_sync.build", return_value=mock_service):
        calendar_sync.add_deadline_to_calendar(user_with_valid_token, "cs101", "2026-09-01", "Midterm", "exam")

    _, kwargs = mock_service.events.return_value.insert.call_args
    assert kwargs["body"]["start"] == {"date": "2026-09-01"}
    assert kwargs["body"]["end"] == {"date": "2026-09-02"}


@pytest.mark.django_db
def test_add_deadline_to_calendar_raises_when_already_synced(isolated_courses_dir, user_with_valid_token):
    storage.append_calendar_sync_record("cs101", {
        "date": "2026-09-01", "title": "Midterm", "type": "exam",
        "google_event_id": "event-abc", "synced_at": "2026-08-20T00:00:00+00:00",
    }, user=user_with_valid_token)

    with patch("agent.services.calendar_sync.build") as build:
        with pytest.raises(calendar_sync.AlreadySyncedError):
            calendar_sync.add_deadline_to_calendar(user_with_valid_token, "cs101", "2026-09-01", "Midterm", "exam")

    build.assert_not_called()


@pytest.mark.django_db
def test_add_deadline_to_calendar_refreshes_an_expired_token_and_persists_it(isolated_courses_dir, db):
    user = User.objects.create_user(username="sub-456", email="alex@example.com")
    account = GoogleCalendarConnection.objects.create(
        user=user,
        access_token="stale-access-token", refresh_token="refresh-token-value",
        token_expiry=timezone.now() - timedelta(hours=1),
    )

    def _fake_refresh(self, request):
        self.token = "refreshed-access-token"
        self.expiry = datetime.now(UTC) + timedelta(hours=1)

    with patch("agent.services.calendar_sync.build", return_value=_mock_calendar_build()), \
         patch("google.oauth2.credentials.Credentials.refresh", _fake_refresh):
        calendar_sync.add_deadline_to_calendar(user, "cs101", "2026-09-01", "Midterm", "exam")

    account.refresh_from_db()
    assert account.access_token == "refreshed-access-token"
    assert account.token_expiry > timezone.now()


@pytest.mark.django_db
def test_add_deadline_to_calendar_raises_calendar_auth_error_when_refresh_fails(isolated_courses_dir, db):
    from google.auth.exceptions import RefreshError

    user = User.objects.create_user(username="sub-789", email="sam@example.com")
    GoogleCalendarConnection.objects.create(
        user=user,
        access_token="stale-access-token", refresh_token="revoked-refresh-token",
        token_expiry=timezone.now() - timedelta(hours=1),
    )

    def _fake_refresh_failure(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    with patch("agent.services.calendar_sync.build") as build, \
         patch("google.oauth2.credentials.Credentials.refresh", _fake_refresh_failure):
        with pytest.raises(calendar_sync.CalendarAuthError):
            calendar_sync.add_deadline_to_calendar(user, "cs101", "2026-09-01", "Midterm", "exam")

    build.assert_not_called()
    assert storage.read_calendar_sync("cs101") == []


@pytest.mark.django_db
def test_add_deadline_to_calendar_records_grant_failed_at_when_refresh_fails(isolated_courses_dir, db):
    from google.auth.exceptions import RefreshError

    user = User.objects.create_user(username="sub-grant-fail", email="grantfail@example.com")
    connection = GoogleCalendarConnection.objects.create(
        user=user,
        access_token="stale-access-token", refresh_token="revoked-refresh-token",
        token_expiry=timezone.now() - timedelta(hours=1),
    )

    def _fake_refresh_failure(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    with patch("google.oauth2.credentials.Credentials.refresh", _fake_refresh_failure):
        with pytest.raises(calendar_sync.CalendarAuthError):
            calendar_sync.add_deadline_to_calendar(user, "cs101", "2026-09-01", "Midterm", "exam")

    connection.refresh_from_db()
    assert connection.grant_failed_at is not None


@pytest.mark.django_db
def test_add_deadline_to_calendar_clears_grant_failed_at_on_successful_refresh(isolated_courses_dir, db):
    user = User.objects.create_user(username="sub-grant-clear", email="grantclear@example.com")
    connection = GoogleCalendarConnection.objects.create(
        user=user,
        access_token="stale-access-token", refresh_token="refresh-token-value",
        token_expiry=timezone.now() - timedelta(hours=1),
        grant_failed_at=timezone.now() - timedelta(days=1),
    )

    def _fake_refresh(self, request):
        self.token = "refreshed-access-token"
        self.expiry = datetime.now(UTC) + timedelta(hours=1)

    with patch("agent.services.calendar_sync.build", return_value=_mock_calendar_build()), \
         patch("google.oauth2.credentials.Credentials.refresh", _fake_refresh):
        calendar_sync.add_deadline_to_calendar(user, "cs101", "2026-09-01", "Midterm", "exam")

    connection.refresh_from_db()
    assert connection.grant_failed_at is None


@pytest.mark.django_db
def test_profile_calendar_connected_false_when_never_connected(django_user_model):
    from agent.views import _profile_payload

    user = django_user_model.objects.create_user(username="never-connected")

    payload = _profile_payload(user)

    assert payload["calendar_connected"] is False


@pytest.mark.django_db
def test_profile_calendar_connected_false_when_grant_failed(django_user_model):
    from agent.views import _profile_payload

    user = django_user_model.objects.create_user(username="grant-failed-user")
    GoogleCalendarConnection.objects.create(
        user=user, access_token="a", refresh_token="r",
        token_expiry=timezone.now() + timedelta(hours=1),
        grant_failed_at=timezone.now(),
    )

    payload = _profile_payload(user)

    assert payload["calendar_connected"] is False


@pytest.mark.django_db
def test_dashboard_and_grades_unaffected_by_revoked_calendar_grant(isolated_courses_dir, django_user_model):
    """A revoked/expired Calendar grant must never break unrelated tabs —
    the dashboard and grades summary don't touch Calendar at all."""
    from rest_framework.test import APIClient

    from agent.models import UserSettings

    user = django_user_model.objects.create_user(username="revoked-grant-user")
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE)
    GoogleCalendarConnection.objects.create(
        user=user, access_token="a", refresh_token="r",
        token_expiry=timezone.now() + timedelta(hours=1),
        grant_failed_at=timezone.now(),
    )
    client = APIClient()
    client.force_authenticate(user=user)

    assert client.get("/api/dashboard/").status_code == 200
    assert client.get("/api/grades/summary/").status_code == 200


@pytest.mark.django_db
def test_add_deadline_to_calendar_raises_calendar_auth_error_on_lazy_refresh_failure_during_execute(
    isolated_courses_dir, user_with_valid_token,
):
    # The stored token looks unexpired (so _get_credentials's pre-emptive
    # `credentials.expired` check doesn't fire), but the user revoked
    # OnTrack's Google access out-of-band — the client library discovers
    # this and raises RefreshError lazily, inside .execute() itself.
    from google.auth.exceptions import RefreshError

    mock_service = MagicMock()
    mock_service.events.return_value.insert.return_value.execute.side_effect = RefreshError("invalid_grant")

    with patch("agent.services.calendar_sync.build", return_value=mock_service):
        with pytest.raises(calendar_sync.CalendarAuthError):
            calendar_sync.add_deadline_to_calendar(user_with_valid_token, "cs101", "2026-09-01", "Midterm", "exam")

    assert storage.read_calendar_sync("cs101") == []


@pytest.mark.django_db
def test_add_deadline_to_calendar_raises_calendar_auth_error_on_http_error(
    isolated_courses_dir, user_with_valid_token,
):
    import httplib2
    from googleapiclient.errors import HttpError

    resp = httplib2.Response({"status": 429})
    mock_service = MagicMock()
    mock_service.events.return_value.insert.return_value.execute.side_effect = HttpError(
        resp, b"Rate Limit Exceeded",
    )

    with patch("agent.services.calendar_sync.build", return_value=mock_service):
        with pytest.raises(calendar_sync.CalendarAuthError):
            calendar_sync.add_deadline_to_calendar(user_with_valid_token, "cs101", "2026-09-01", "Midterm", "exam")

    assert storage.read_calendar_sync("cs101") == []


@pytest.mark.django_db
def test_add_deadline_to_calendar_raises_calendar_auth_error_on_network_error(
    isolated_courses_dir, user_with_valid_token,
):
    mock_service = MagicMock()
    mock_service.events.return_value.insert.return_value.execute.side_effect = OSError("network unreachable")

    with patch("agent.services.calendar_sync.build", return_value=mock_service):
        with pytest.raises(calendar_sync.CalendarAuthError):
            calendar_sync.add_deadline_to_calendar(user_with_valid_token, "cs101", "2026-09-01", "Midterm", "exam")

    assert storage.read_calendar_sync("cs101") == []


@pytest.mark.django_db
def test_add_deadline_to_calendar_raises_calendar_auth_error_when_user_has_no_google_account(
    isolated_courses_dir, db,
):
    # Every DRF view in this app requires only IsAuthenticated, which admits
    # any authenticated Django user — not just ones with a linked
    # GoogleAccount (e.g. a createsuperuser account, or this fixture's own
    # plain user).
    user = User.objects.create_user(username="no-google-account")

    with patch("agent.services.calendar_sync.build") as build:
        with pytest.raises(calendar_sync.CalendarAuthError):
            calendar_sync.add_deadline_to_calendar(user, "cs101", "2026-09-01", "Midterm", "exam")

    build.assert_not_called()
    assert storage.read_calendar_sync("cs101") == []
