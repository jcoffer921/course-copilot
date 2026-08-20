import pytest
from django.contrib.auth.models import User
from django.db.utils import IntegrityError
from django.utils import timezone


@pytest.mark.django_db
def test_creates_google_account_linked_to_user():
    from agent.models import GoogleAccount

    user = User.objects.create_user(username="jordan", email="jordan@example.com")
    account = GoogleAccount.objects.create(
        user=user, google_sub="1234567890", email="jordan@example.com",
        access_token="access-token-value", refresh_token="refresh-token-value",
        token_expiry=timezone.now(),
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
        access_token="a", refresh_token="r", token_expiry=timezone.now(),
    )

    with pytest.raises(IntegrityError):
        GoogleAccount.objects.create(
            user=user2, google_sub="dup-sub", email="alex@example.com",
            access_token="a", refresh_token="r", token_expiry=timezone.now(),
        )
