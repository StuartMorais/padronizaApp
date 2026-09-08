from __future__ import annotations

from app.core.application_logging import configure_application_logging, report_exception


def test_exception_report_writes_rotating_log_and_has_error_id(tmp_path):
    log_path = configure_application_logging(tmp_path)
    try:
        raise ValueError("example failure")
    except ValueError as exc:
        report = report_exception("unit_test", exc, context={"template_id": "abc"})

    assert report.error_id
    assert "unit_test" in report.details
    assert "template_id" in report.details
    assert log_path.exists()
    text = log_path.read_text(encoding="utf-8")
    assert report.error_id in text
    assert "example failure" in text
