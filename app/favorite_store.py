from __future__ import annotations

import json
from collections.abc import Iterable

from PySide6.QtCore import QByteArray, QSettings

from app.runtime_settings import APPLICATION, ORGANIZATION


class FavoriteStore:
    """
    Store favorite template IDs in QSettings.

    Only IDs are persisted. Names, categories, versions, and file paths always
    come from the active template packages, which prevents stale metadata.
    """

    SETTINGS_KEY = "templates/favorites"

    def __init__(
        self,
        settings: QSettings | None = None,
    ) -> None:
        self.settings = settings or QSettings(
            ORGANIZATION,
            APPLICATION,
        )

    def favorite_ids(self) -> list[str]:
        raw_value = self.settings.value(
            self.SETTINGS_KEY,
            [],
        )

        if raw_value is None:
            values: list[object] = []

        elif isinstance(raw_value, str):
            stripped = raw_value.strip()

            if not stripped:
                values = []

            elif stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    parsed = [stripped]

                values = (
                    list(parsed)
                    if isinstance(parsed, list)
                    else [parsed]
                )
            else:
                values = [stripped]

        elif isinstance(
            raw_value,
            (list, tuple, set),
        ):
            values = list(raw_value)

        else:
            values = [raw_value]

        result: list[str] = []
        seen: set[str] = set()

        for value in values:
            template_id = self._setting_value_to_text(value)

            if (
                not template_id
                or template_id in seen
            ):
                continue

            seen.add(template_id)
            result.append(template_id)

        return result

    @staticmethod
    def _setting_value_to_text(value: object) -> str:
        if isinstance(value, QByteArray):
            return bytes(value).decode(
                "utf-8",
                errors="ignore",
            ).strip()
        if isinstance(value, memoryview):
            return value.tobytes().decode(
                "utf-8",
                errors="ignore",
            ).strip()
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).decode(
                "utf-8",
                errors="ignore",
            ).strip()
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return f"{value}".strip()
        return ""

    def is_favorite(
        self,
        template_id: str,
    ) -> bool:
        return (
            str(template_id).strip()
            in self.favorite_ids()
        )

    def set_favorite(
        self,
        template_id: str,
        favorite: bool,
    ) -> bool:
        template_id = str(
            template_id
        ).strip()

        if not template_id:
            return False

        favorite_ids = self.favorite_ids()
        currently_favorite = (
            template_id in favorite_ids
        )

        if favorite and not currently_favorite:
            favorite_ids.append(template_id)

        elif (
            not favorite
            and currently_favorite
        ):
            favorite_ids = [
                value
                for value in favorite_ids
                if value != template_id
            ]

        else:
            return currently_favorite

        self._save(favorite_ids)
        return favorite

    def toggle(
        self,
        template_id: str,
    ) -> bool:
        favorite = not self.is_favorite(
            template_id
        )

        return self.set_favorite(
            template_id,
            favorite,
        )

    def remove(
        self,
        template_id: str,
    ) -> None:
        self.set_favorite(
            template_id,
            False,
        )

    def prune(
        self,
        active_template_ids: Iterable[str],
    ) -> bool:
        active_ids = {
            str(template_id).strip()
            for template_id
            in active_template_ids
            if str(template_id).strip()
        }

        current = self.favorite_ids()
        cleaned = [
            template_id
            for template_id in current
            if template_id in active_ids
        ]

        if cleaned == current:
            return False

        self._save(cleaned)
        return True

    def _save(
        self,
        favorite_ids: list[str],
    ) -> None:
        self.settings.setValue(
            self.SETTINGS_KEY,
            favorite_ids,
        )
        self.settings.sync()
