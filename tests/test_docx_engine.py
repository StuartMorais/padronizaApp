import tempfile
import unittest
from pathlib import Path

from docx import Document

from app.docx_engine import generate_docx


class DocxEngineTests(unittest.TestCase):
    """
    Automated tests for the DOCX generation engine.
    """

    def test_replaces_paragraph_and_table_placeholders(
        self,
    ) -> None:
        """
        Confirm that the engine replaces placeholders in:

        - A normal paragraph
        - A table cell
        """

        # TemporaryDirectory creates a folder that is automatically
        # removed after the test finishes.
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            template_path = (
                temp_path / "template.docx"
            )

            output_path = (
                temp_path / "output.docx"
            )

            # Create a small DOCX template for the test.
            document = Document()

            document.add_paragraph(
                "Company: {{company.name}}"
            )

            table = document.add_table(
                rows=1,
                cols=1,
            )

            table.cell(0, 0).text = (
                "Process: {{process.number}}"
            )

            document.save(template_path)

            # Run the document-generation engine.
            generate_docx(
                template_path=template_path,
                output_path=output_path,
                values={
                    "company.name": "Example Ltd.",
                    "process.number": "001/2026",
                },
            )

            # Open the generated document.
            result = Document(output_path)

            # Confirm that the paragraph was replaced.
            self.assertEqual(
                result.paragraphs[0].text,
                "Company: Example Ltd.",
            )

            # Confirm that the table cell was replaced.
            self.assertEqual(
                result.tables[0].cell(0, 0).text,
                "Process: 001/2026",
            )


if __name__ == "__main__":
    unittest.main()