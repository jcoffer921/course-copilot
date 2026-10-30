"""The one line of plain text a faculty member can print above the title of exported plans.

It is exactly what they type (their own institution and department wording) and nothing more: no logo,
no wording added on their behalf. It is normalized to a single safe line, and the export endpoint reads
the saved value itself, never one supplied by the browser.
"""

import unicodedata

from ..models import UserSettings

MAX_LENGTH = 160


def normalize(value) -> str:
    """Trim, fold every kind of whitespace and line break into single spaces, drop control and
    invisible formatting characters (including bidirectional overrides), and cap the length."""
    if not isinstance(value, str):
        return ""
    visible = "".join(
        " " if character.isspace() else character
        for character in value
        if character.isspace() or not unicodedata.category(character).startswith("C")
    )
    return " ".join(visible.split())[:MAX_LENGTH].rstrip()


def get_for_user(user) -> str:
    return UserSettings.objects.filter(user=user).values_list("export_header_line", flat=True).first() or ""


def set_for_user(user, line) -> str:
    row, _ = UserSettings.objects.get_or_create(user=user)
    row.export_header_line = normalize(line)
    row.save(update_fields=["export_header_line", "updated_at"])
    return row.export_header_line
