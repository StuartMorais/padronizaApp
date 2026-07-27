from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.template_repository import (
    TemplateRepository,
)


@dataclass(frozen=True)
class TemplatePackage:
    template_id: str
    name: str
    description: str
    category: str
    version: str
    source_path: Path
    fields: list[dict[str, Any]]
    output_filename: str
    config: dict[str, Any]


def discover_templates(
    templates_dir: Path,
) -> list[TemplatePackage]:
    """
    Discover active templates through TemplateRepository.

    This uses the same compatibility normalization as the template editor, so
    older templates appear consistently in both the main window and manager.
    """

    repository = TemplateRepository(
        templates_dir
    )
    packages: list[TemplatePackage] = []

    for summary in repository.list_templates():
        template_id = str(
            summary["id"]
        )

        try:
            config = repository.read_config(
                template_id
            )
            source_path = (
                repository.get_source_path(
                    template_id
                )
            )
        except Exception:
            continue

        template = config["template"]
        output = config.get(
            "output",
            {},
        )

        packages.append(
            TemplatePackage(
                template_id=template_id,
                name=str(
                    template.get(
                        "name",
                        template_id,
                    )
                ),
                description=str(
                    template.get(
                        "description",
                        "",
                    )
                ),
                category=str(
                    template.get(
                        "category",
                        "",
                    )
                ),
                version=str(
                    template.get(
                        "version",
                        "1.0",
                    )
                ),
                source_path=source_path,
                fields=[
                    dict(field)
                    for field in config.get(
                        "fields",
                        [],
                    )
                    if isinstance(
                        field,
                        dict,
                    )
                ],
                output_filename=str(
                    output.get(
                        "filename_pattern",
                        "{{template.name}}.docx",
                    )
                ),
                config=config,
            )
        )

    packages.sort(
        key=lambda package: (
            package.name.casefold(),
            package.template_id.casefold(),
        )
    )
    return packages
