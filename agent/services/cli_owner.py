"""Resolves the single 'owner' Django user the 9 CLI management commands
operate as. These commands are dev/debug tools only — real students always
go through the web API, where request.user comes from an authenticated
session. The CLI has no such session, so it needs one designated account
instead, chosen the same way the rest of the app identifies people: by
email (CLAUDE.md/README's existing ALLOWED_GOOGLE_EMAILS convention), not
username or a --user flag."""

import os

from django.contrib.auth.models import User
from django.core.management.base import CommandError


def resolve_owner_user() -> User:
    """Returns the User whose email matches CLI_OWNER_EMAIL. Raises
    CommandError (not a raw exception) if the env var is unset or no
    matching user exists yet — fails loudly with an actionable message,
    per CLAUDE.md's "fails loudly" convention, since a silent fallback here
    would write CLI output into the wrong (or a newly-created) user's
    course directory."""
    email = os.environ.get("CLI_OWNER_EMAIL")
    if not email:
        raise CommandError(
            "CLI_OWNER_EMAIL environment variable is not set — the CLI commands need "
            "one designated owner account to operate as. Set it to the email of your "
            "own Google-signed-in account, e.g.: set CLI_OWNER_EMAIL=you@example.com"
        )
    try:
        return User.objects.get(email=email)
    except User.DoesNotExist:
        raise CommandError(
            f"no user found with email '{email}' — sign in through the web UI with "
            "this Google account at least once first, so its User row exists."
        )
