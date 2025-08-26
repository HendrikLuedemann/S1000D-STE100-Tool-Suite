ASD-STE100 (Issue 9) linter — Windows-friendly, with built-in PDF path

Builds (on first run or with --rebuild):
  - ste_issue9_approved_words.txt        -> official approved words (+ verb inflections + noun plurals)
  - ste_issue9_forbidden_words.txt       -> official forbidden words (lowercase headwords only)
  - ste_issue9_all_caps_words.txt        -> ALL-CAPS tokens scanned from the full PDF (used as extra allow-list)

Lint flags:
  - Forbidden words (from official list)
  - Unapproved words (not in approved list AND not in all-caps list)
  - Sentences > N words (default 20)
  - Simple passive voice (be + VERBed)

Quick start (PowerShell):
```
python ste100_linter.py --rebuild --text "The operator starts the system and does the procedure in 25 minutes."
```
