# Phase 3 follow-up backlog (post-checkpoint)

File as GitHub issues with labels `revamp` and `phase-3` when UAT finds gaps.

| Topic | Notes |
| --- | --- |
| Vision OCR transport | Wire `complete_structured_vision` to a configured multimodal model; keep confirm step and inferred flags. |
| Full SessionEditor logged mode | Complete P2-3 (#1829) parity in `v2-session-editor` (JSON panel, fitness preview, template save). |
| Planned editor TSS live sync | Debounced server dry-run for exercise edits (match mock “updates as you type”). |
| Photo HEIC transcoding | Server-side convert HEIC→JPEG when browser upload mime is inconsistent. |
| E2E drag-and-drop | Browser test for board DnD + rule bounce copy. |