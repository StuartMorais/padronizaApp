from pathlib import Path

from checklist_app.scanner import SCANNER_VERSION, analyze_document, build_template_from_scan

FIXTURE = Path(__file__).parent / "fixtures" / "checklist_administrativo_lei_14133.pdf"


def test_official_pdf_scanner_recovers_full_structure():
    result = analyze_document(FIXTURE)
    report = result.report

    assert report.scanner_version == SCANNER_VERSION == 6
    assert report.structure_kind == "official_singra_checklist"
    assert report.page_count == 8
    assert report.table_header_pages == 8
    assert len(report.sections) == 5
    assert len(result.candidates) == 40
    assert report.blocking_issue_count == 0
    assert report.review_count == 0

    numbers = [item["number"] for item in result.candidates]
    assert numbers[:6] == ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6"]
    assert "2.2" in numbers
    assert "2.2.1" not in numbers  # nested content belongs to the 2.2 checklist row
    assert "2.2.2" in numbers
    assert "4.9" in numbers
    assert numbers[-3:] == ["5.2", "5.3", "5.4"]


def test_official_pdf_scanner_maps_needed_columns_by_geometry_without_platform_code():
    result = analyze_document(FIXTURE)
    by_number = {item["number"]: item for item in result.candidates}

    item = by_number["1.1"]
    assert "codigo" not in item
    assert "Inciso VII" in item["normativo"]
    assert item["situacao"] == ""
    assert item["observacao"] == "Pendente"
    assert item["source_page"] == 1
    assert item["source"] == "pdf_table_geometry"
    assert item["confidence"] >= 0.95
    assert item["selected"] is True

    assert by_number["1.6"]["source_page"] == 2
    assert by_number["5.2"]["source_page"] == 8


def test_scanner_extracts_document_level_metadata():
    result = analyze_document(FIXTURE)
    assert result.metadata["processoPbdoc"] == "SDH-PRC-2026/01518"
    assert "codigoObjeto" not in result.metadata
    assert "Aquisição saco plástico" in result.metadata["objeto"]
    assert result.metadata["baseLegal"] == "LEI Nº 14.133/21"
    assert "CHECKLIST I" in result.metadata["title"]


def test_reviewed_scan_builds_five_section_template_without_losing_evidence():
    result = analyze_document(FIXTURE)
    reviewed = result.candidate_list()
    for candidate in reviewed:
        candidate["accepted_by_user"] = True
        candidate["reviewed_by_user"] = True

    template = build_template_from_scan(result, reviewed)
    assert [(section["number"], len(section["items"])) for section in template["sections"]] == [
        ("1", 17), ("2", 5), ("3", 3), ("4", 11), ("5", 4)
    ]
    assert template["sourceMetadata"]["processoPbdoc"] == "SDH-PRC-2026/01518"
    first = template["sections"][0]["items"][0]
    assert "codigo" not in first
    assert first["scanPage"] == 1
    assert first["scanSource"] == "pdf_table_geometry"
    assert first["scanCandidateId"]
    assert first["scanEvidence"]


def test_review_can_exclude_candidate_before_template_creation():
    result = analyze_document(FIXTURE)
    reviewed = result.candidate_list()
    for candidate in reviewed:
        candidate["accepted_by_user"] = candidate["number"] != "1.5"
        candidate["reviewed_by_user"] = True
    template = build_template_from_scan(result, reviewed)
    numbers = [item["number"] for section in template["sections"] for item in section["items"]]
    assert len(numbers) == 39
    assert "1.5" not in numbers
