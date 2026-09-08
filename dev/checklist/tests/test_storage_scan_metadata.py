from checklist_app.storage import normalize_template


def test_scan_metadata_survives_normalization():
    template = normalize_template({
        "id": "x",
        "title": "Checklist",
        "sourceMetadata": {"processoPbdoc": "SDH-PRC-2026/01518"},
        "scanReport": {"scanner_version": 6, "candidate_count": 1},
        "scanCandidates": [{"candidate_id": "c1", "number": "1.1"}],
        "sections": [{
            "number": "1",
            "title": "SEÇÃO",
            "items": [{
                "number": "1.1",
                "documento": "Documento",
                "codigo": "LEGACY-SIA-CODE",
                "situacao": "",
                "scanCandidateId": "c1",
                "scanSource": "pdf_table_geometry",
                "scanPage": 1,
                "scanRect": [1, 2, 3, 4],
                "scanConfidenceValue": 0.97,
                "scanDimensions": {"structure": 1.0},
                "scanReviewed": True,
            }],
        }],
    })
    assert template["sourceMetadata"]["processoPbdoc"] == "SDH-PRC-2026/01518"
    assert template["scanReport"]["scanner_version"] == 6
    assert template["scanCandidates"][0]["candidate_id"] == "c1"
    item = template["sections"][0]["items"][0]
    assert "codigo" not in item
    assert item["situacao"] == ""
    assert item["scanPage"] == 1
    assert item["scanSource"] == "pdf_table_geometry"
