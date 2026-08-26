from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.fields import FieldDefinition
from app.repositories.templates import TemplateRepository


@dataclass(frozen=True)
class TemplatePackage:
    template_id: str
    name: str
    description: str
    category: str
    version: str
    source_path: Path
    fields: list[FieldDefinition]
    output_filename: str
    config: dict[str, Any]


def discover_templates(
    templates_dir: Path,
) -> list[TemplatePackage]:
    """Discover usable active templates, preserving compatibility normalization."""

    packages, _issues = discover_templates_with_issues(templates_dir)
    return packages


def discover_templates_with_issues(
    templates_dir: Path,
) -> tuple[list[TemplatePackage], list[dict[str, str]]]:
    """Discover templates and return structured failures instead of hiding them."""

    repository = TemplateRepository(templates_dir)
    packages: list[TemplatePackage] = []
    summaries = repository.list_templates()
    issues = repository.list_discovery_issues()

    for summary in summaries:
        template_id = str(summary["id"])
        try:
            config = repository.read_config(template_id)
            source_path = repository.get_source_path(template_id)
        except Exception as exc:
            issues.append(
                {
                    "template_id": template_id,
                    "folder": str(summary.get("folder", "")),
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            continue

        template = config["template"]
        output = config.get("output", {})
        packages.append(
            TemplatePackage(
                template_id=template_id,
                name=str(template.get("name", template_id)),
                description=str(template.get("description", "")),
                category=str(template.get("category", "")),
                version=str(template.get("version", "1.0")),
                source_path=source_path,
                fields=[
                    FieldDefinition(field)
                    for field in config.get("fields", [])
                    if isinstance(field, dict)
                ],
                output_filename=str(
                    output.get("filename_pattern", "{{template.name}}.docx")
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
    issues.sort(key=lambda issue: str(issue.get("template_id", "")).casefold())
    return packages, issues
