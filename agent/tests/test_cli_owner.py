"""Tests for agent/services/cli_owner.py's owner-resolution helper."""
import pytest
from django.core.management.base import CommandError

from agent.services import cli_owner


@pytest.mark.django_db
def test_resolve_owner_user_finds_user_by_email(monkeypatch, django_user_model):
    django_user_model.objects.create_user(username="abc123", email="dev@example.com")
    monkeypatch.setenv("CLI_OWNER_EMAIL", "dev@example.com")
    user = cli_owner.resolve_owner_user()
    assert user.email == "dev@example.com"


def test_resolve_owner_user_raises_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("CLI_OWNER_EMAIL", raising=False)
    with pytest.raises(CommandError, match="CLI_OWNER_EMAIL"):
        cli_owner.resolve_owner_user()


@pytest.mark.django_db
def test_resolve_owner_user_raises_when_no_matching_user(monkeypatch):
    monkeypatch.setenv("CLI_OWNER_EMAIL", "nobody@example.com")
    with pytest.raises(CommandError, match="nobody@example.com"):
        cli_owner.resolve_owner_user()
