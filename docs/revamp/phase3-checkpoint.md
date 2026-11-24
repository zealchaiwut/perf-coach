# Phase 3 checkpoint — plan against the mock

Manual UAT checklist for sprint 141 (issues #1835–#1847). Compare
`docs/revamp/mocks/preview/TrainingWeek.html` and `TrainingPlanEdit.html`
beside `/v2/training/plan`.

## Reviewer checklist

- [ ] Load plan chart, this-week card, week board, and Log agree on current week TSS (race estimate included).
- [ ] Drag a support session to a blocked day — bounce reason shown; repeat on a legal day — move persists.
- [ ] Type a coach week, confirm import, re-import with one line changed (locked coach rows replaced).
- [ ] Photo import: upload disabled with plain message when vision LLM is off; typed paste still works.
- [ ] Open planned editor from `+` on a day; plyo library entry disabled in race week with rule reason.
- [ ] Suggest sessions on under-target week; apply; week total moves toward target.
- [ ] Break plan settings (invalid block/race) and confirm settings error surfaces on plan tab.

## Automated smoke

`tests/test_phase3_checkpoint__1847.py` — static contracts for Phase 3 routes and pages.

## Follow-up candidates (label `revamp`, `phase-3`)

See `docs/revamp/phase3-followups.md`.