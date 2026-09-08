# ChecklistPython

Python/PySide6 version of the checklist application.

This project replaces the HTML/Electron prototype with a Windows desktop app that keeps the same local JSON data model and adds a structure-first scanner inspired by Padroniza.

## What changed in this version

The interface was rebuilt again to make the checklist itself easier to read:

- **Área de trabalho** now lives in a single top navigation bar with **Início**, **Checklists**, and **Scanner**.
- The checklist library is the only left-side panel, removing the previous double-sidebar feeling.
- The app has two complete themes: **Modo claro** and **Modo escuro**. The whole interface changes theme together and the choice is remembered.
- The main checklist view imitates the official verification-sheet layout instead of splitting the user across many small lists.
- Sections appear as wide collapsible bars, like the original app: they start closed and open with `▶ / ▼`.
- Selected sections can be renamed with **Renomear seção**; custom names and capitalization are saved and exported.
- **Expandir tudo** and **Recolher tudo** are available above the checklist.
- Items appear in one large editable table with columns for item, document/information, normative reference, S/N/NA, sheet/page, and observation.
- The bottom panel keeps the original app idea of **Documentos necessários**, showing description, minimum documents, and review notes for the selected item.
- Scanner output is treated as something to review before using as final data.
- The scanner now follows the Padroniza V6 safety model: structure extraction, detector evidence, confidence, invariants, human review, diagnostics and technical report.
- Official SINGRA checklist PDFs are read by physical table geometry, so PDF text extraction order cannot mix the Documento, Normativo, S/N/NA, Folha and Observação columns.
- PDF export follows the same complete checklist structure.

## Features

- Reads and saves existing checklist data from `%APPDATA%\checklist-app\data\checklistTemplates.json`.
- Creates automatic backups before saving.
- Scans DOCX, DOCM, and PDF files into checklist sections/items.
- Uses a Padroniza-style six-stage scanner pipeline and review-first policy.
- Detects the repeated physical grid used by official SINGRA checklist PDFs.
- Detects numbered sections such as `1. DAS FORMALIDADES...`.
- Detects real checklist rows such as `1.1`, `2.2`, and `4.9` while keeping nested numbering inside its parent row when the PDF grid shows one row.
- Maps normative reference, S/N/NA, Folha and Observação by column geometry. The SIAGOV platform-code column is intentionally ignored.
- Extracts document-level process metadata such as the PBDOC process and object when present.
- Stores source page, source rectangle, confidence dimensions and scanner evidence on imported items.
- Provides `Revisar itens detectados`, `Executar diagnóstico`, and `Relatório técnico` tools.
- Lets the user review/edit scanned checklist items through an official-sheet style table plus a focused guidance panel.
- Exports the full selected checklist to PDF with the same application columns; the source SIAGOV platform-code column is intentionally omitted.
- Includes a bundled application icon for the window, portable EXE, and installer.
- Imports and exports individual checklists as portable JSON files without replacing the local checklist library.
- Preserves the checklist table scroll position when sections are expanded/collapsed or S/N/NA values are changed.

### Scanner/navigation fixes in this build

- The top **Scanner** navigation and the checklist-library **Abrir scanner** button now open the same canonical Scanner workspace.
- `QComboBox` is explicitly imported for the S/N/NA controls. This fixes the crash that interrupted section expansion after the first item.
- Expanded sections now finish rendering all of their items and can be collapsed normally.
- The **Código Plataforma** field was removed from scanner candidates, saved checklist items, review UI, checklist sheet, search, and PDF export. The source column is still used only as a geometric separator when reading the official PDF grid.

### JSON portátil e posição da folha

Use **JSON ▾ → Exportar checklist ativo…** para salvar somente o checklist selecionado em um arquivo compartilhável. **Importar checklist JSON…** adiciona o arquivo à biblioteca local; se o mesmo ID já existir, ele entra como uma cópia em vez de sobrescrever o checklist atual.

Ao expandir/recolher seções ou alterar a opção **S / N / NA**, a folha mantém a posição de rolagem atual em vez de voltar para o topo.

## Local development

```powershell
cd "C:\Users\ADM\Desktop\Codigos\Python\ChecklistPython"

py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Build locally on Windows

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\scripts\build_github.ps1 -Version v1.0.0 -SkipInstaller
```

To build the installer too, install Inno Setup 6 and run:

```powershell
.\scripts\build_github.ps1 -Version v1.0.0
```

Build outputs are created in:

```text
dist\release\
```

## GitHub release workflow

The workflow is located at:

```text
.github\workflows\release-windows.yml
```

It works like the Padroniza release flow:

1. Go to **Actions**.
2. Open **Gerar release do ChecklistPython para Windows**.
3. Click **Run workflow**.
4. Choose `patch`, `minor`, or `major`.
5. The workflow resolves the next SemVer tag, builds the Windows portable EXE, builds the installer, calculates SHA-256 hashes, uploads the workflow artifact, and publishes the files directly to GitHub Releases.

The workflow also supports semantic tag pushes such as:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

## Release assets

A release publishes:

```text
ChecklistPython-vX.Y.Z.exe
ChecklistPython-Setup-vX.Y.Z.exe
SHA256SUMS.txt
```

## Important notes

- Do not commit `.venv`, `build`, `dist`, `__pycache__`, or local runtime data.
- The app keeps using `%APPDATA%\checklist-app\data\checklistTemplates.json`, so existing Electron checklist data remains visible to the Python app.
- The scanner now mirrors Padroniza Scanner V6's verification/review architecture, but uses checklist-specific detectors rather than Word-template field detectors.
- `tests/fixtures/checklist_administrativo_lei_14133.pdf` is a permanent real-document scanner benchmark.

### Rolagem mais suave

As listas, a folha principal do checklist, os painéis com rolagem e os editores multilinha usam rolagem em pixels com passos menores. Isso evita saltos grandes quando uma linha do checklist tem bastante texto.
