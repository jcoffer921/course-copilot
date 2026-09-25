import pytest
from django.contrib.auth.models import User
from django.db.utils import IntegrityError


@pytest.mark.django_db
def test_creates_google_account_linked_to_user():
    from agent.models import GoogleAccount

    user = User.objects.create_user(username="jordan", email="jordan@example.com")
    account = GoogleAccount.objects.create(
        user=user, google_sub="1234567890", email="jordan@example.com",
    )

    assert account.user == user
    assert user.google_account == account
    assert str(account) == "jordan@example.com"


@pytest.mark.django_db
def test_google_sub_must_be_unique():
    from agent.models import GoogleAccount

    user1 = User.objects.create_user(username="jordan")
    user2 = User.objects.create_user(username="alex")
    GoogleAccount.objects.create(
        user=user1, google_sub="dup-sub", email="jordan@example.com",
    )

    with pytest.raises(IntegrityError):
        GoogleAccount.objects.create(
            user=user2, google_sub="dup-sub", email="alex@example.com",
        )


def test_private_state_models_require_an_owner():
    from agent.models import (
        CalendarSyncRecord,
        CourseSession,
        CustomEvent,
        FlashcardProgress,
        GradeItem,
        MasteryScore,
        Notification,
        QuizAttempt,
        SavedSite,
    )

    for model in (
        FlashcardProgress,
        GradeItem,
        CalendarSyncRecord,
        CustomEvent,
        Notification,
        SavedSite,
        QuizAttempt,
        MasteryScore,
        CourseSession,
    ):
        assert model._meta.get_field("user").null is False
