# Scanner V5 — Review-First Detection

**Baseline:** 2026-08-26

Scanner V5 changes the automatic-detection contract without discarding the structural intelligence built for Scanner V4. The scanner may discover a broad set of candidates, but discovery no longer implies silent application. A selection policy decides which candidates are safe to preselect and which require explicit review.

## Pipeline

```text
source document
→ normalized extraction + fingerprint
→ structural ownership / tables / sections / roles
→ independent detector passes
→ candidate evidence and semantic/type inference
→ selection policy
→ human review where needed
→ transactional tag application
→ strict normal-scanner round trip
```

## Reliability rules

- Explicit/manual tags and protected structures remain authoritative.
- Structural-table ownership runs before ordinary cell heuristics.
- Strong, internally consistent evidence may be preselected.
- Medium-confidence, conflicting, or negatively evidenced candidates remain visible but unselected by default.
- Detector output preserves evidence, source/location metadata, and a document fingerprint.
- A single standalone `OU` is sufficient for a two-option long-choice block; three choices are not required.
- A contiguous colored run inside otherwise static prose may become an inline single-choice field when it contains two to five explicit `OU` alternatives. Only the colored span is replaced, preserving the sentence around it.
- The scanner never treats an LLM/semantic guess as permission to directly manipulate OOXML.
- Accepted modifications are staged and must survive strict re-scan before publication.

## Main modules

- `app/services/template_scanning.py` — application-level orchestration used by the template editor. One call returns authoritative fields plus additional review candidates without collapsing the internal detector stages.
- `extraction.py` — normalized source/fingerprint extraction contract.
- `passes.py` — explicit detector-pass orchestration.
- `selection_policy.py` — automatic-preselection policy.
- `structure.py`, `table_structure.py`, `roles.py` — Scanner V4 structural intelligence retained by V5.
- `report.py`, `models.py`, `candidates.py` — candidate/evidence/report contracts.

## Template-editor UX

The normal authoring flow exposes one primary **Localizar campos** button. That button does **not** merge the scanner into one heuristic: it calls the orchestration service, which first synchronizes deterministic Padroniza tags/native Word or reconstructed PDF controls and then runs the review-first untagged detector. Only the heuristic additions open the review dialog. **Diagnóstico** remains a separate secondary action because validation and field discovery are different operations.

## Product direction

The next reliability step is calibration against real failure documents and per-template learned mappings. Known templates should eventually reuse a confirmed mapping/fingerprint rather than rediscovering every field from zero. AI may assist semantic classification, but deterministic extraction remains responsible for document geometry, ownership, and tag placement.

## DFD regression added 2026-08-26

The real DFD fixture now permanently asserts both of the following:

1. `5.1.1. Não se aplica` + `OU` + the standard PCA justification becomes a two-option single-choice field.
2. In section 7, the red inline phrase `área técnica competente ou à equipe de planejamento da contratação` becomes a two-option single-choice field (`área técnica competente` / `equipe de planejamento da contratação`) without replacing the surrounding dispatch sentence.
