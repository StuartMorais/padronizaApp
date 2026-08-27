from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.document.detection.detector import clear_detection_cache, detect_docx_field_candidates


BENCHMARK_ROOT = ROOT / "tests" / "fixtures" / "semantic_v6"


def _matches(candidate: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key in ("field_id", "type", "source"):
        if key in expected and str(candidate.get(key, "")) != str(expected[key]):
            return False
    if "default_value" in expected and candidate.get("default_value") != expected["default_value"]:
        return False
    return True


def run_benchmark() -> dict[str, int]:
    expected_files = sorted(BENCHMARK_ROOT.glob("*.expected.json"))
    if not expected_files:
        raise SystemExit("Semantic benchmark: nenhum contrato .expected.json encontrado.")

    required_total = 0
    required_found = 0
    unexpected_total = 0
    preselected_total = 0
    failures: list[str] = []

    for expected_path in expected_files:
        config = json.loads(expected_path.read_text(encoding="utf-8"))
        source = expected_path.with_name(expected_path.name.replace(".expected.json", ".docx"))
        if not source.exists():
            failures.append(f"{expected_path.name}: DOCX correspondente ausente ({source.name}).")
            continue

        clear_detection_cache()
        candidates = detect_docx_field_candidates(source, semantic_enabled=True)
        required = [dict(item) for item in config.get("required_candidates", []) if isinstance(item, dict)]
        required_total += len(required)

        matched_indexes: set[int] = set()
        for spec in required:
            match_index = next(
                (index for index, candidate in enumerate(candidates) if index not in matched_indexes and _matches(candidate, spec)),
                None,
            )
            if match_index is None:
                failures.append(f"{source.name}: candidato obrigatório ausente/incorreto: {spec}")
            else:
                required_found += 1
                matched_indexes.add(match_index)

        unexpected = [
            candidate
            for index, candidate in enumerate(candidates)
            if index not in matched_indexes
        ]
        unexpected_total += len(unexpected)
        maximum_unexpected = int(config.get("maximum_unexpected_candidates", 0) or 0)
        if len(unexpected) > maximum_unexpected:
            failures.append(
                f"{source.name}: {len(unexpected)} candidato(s) inesperado(s), limite {maximum_unexpected}: "
                + ", ".join(str(item.get("field_id", "?")) for item in unexpected)
            )

        fresh_semantic = [
            item for item in candidates
            if str(item.get("source", "")) in {"semantic_inline", "semantic_prose", "repeatable_list"}
            and bool(item.get("selected", False))
        ]
        preselected_total += len(fresh_semantic)
        maximum_preselected = int(config.get("maximum_fresh_semantic_preselected", 0) or 0)
        if len(fresh_semantic) > maximum_preselected:
            failures.append(
                f"{source.name}: {len(fresh_semantic)} descoberta(s) semântica(s) fresca(s) foram pré-selecionadas."
            )

    if failures:
        print("Semantic benchmark FAILED")
        for failure in failures:
            print(" -", failure)
        raise SystemExit(1)

    print(
        "Semantic benchmark PASS: "
        f"{required_found}/{required_total} obrigatórios; "
        f"{unexpected_total} inesperados; "
        f"{preselected_total} descobertas semânticas pré-selecionadas."
    )
    return {
        "required_total": required_total,
        "required_found": required_found,
        "unexpected": unexpected_total,
        "fresh_semantic_preselected": preselected_total,
    }


if __name__ == "__main__":
    run_benchmark()
