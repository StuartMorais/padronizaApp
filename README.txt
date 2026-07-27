CHECKBOX SELECTION FIX
======================

Replace:

app/widgets/document_form.py
app/placeholder_scanner.py
app/template_repository.py
app/template_manager/template_editor_dialog.py
app/docx_engine.py

Behavior:

- A checkbox is no longer a required confirmation.
- Unchecked is a valid value.
- Every checkbox remains in the generated document.
- Checked:   ☑
- Unchecked: ☐
- New scans save checkbox fields with required=false.
- Old checkbox required=true values are normalized to false.
- The template editor disables Required for checkbox fields.
- Placeholder, modern Word, and legacy Word checkbox fields are supported.

After replacement:

Remove-Item -Recurse -Force .\app\__pycache__ -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\app\widgets\__pycache__ -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\app\template_manager\__pycache__ -ErrorAction SilentlyContinue

.\.venv\Scripts\python.exe main.py

Open each old template in Edit and save it once, or scan it again, to rewrite
old checkbox required flags in template.json.
