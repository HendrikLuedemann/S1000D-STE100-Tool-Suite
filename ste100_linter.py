#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
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
  python ste100_linter.py --rebuild --pdf "C:\\Users\\luede\\OneDrive\\Desktop\\Linter BA\\STE100.pdf" --text "The operator starts the system and does the procedure in 25 minutes."
"""

import os
import re
import sys
import csv
import argparse
from typing import List, Dict, Tuple, Set

# --------- EDIT THIS if your PDF is elsewhere ----------
PDF_PATH = r"C:\Users\luede\OneDrive\Desktop\Linter BA\STE100.pdf"
# -------------------------------------------------------

# Save/read wordlists next to this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APPROVED_PATH = os.path.join(BASE_DIR, "ste_issue9_approved_words.txt")
FORBIDDEN_PATH = os.path.join(BASE_DIR, "ste_issue9_forbidden_words.txt")
ALLCAPS_PATH   = os.path.join(BASE_DIR, "ste_issue9_all_caps_words.txt")

# ---------------------- PDF parsing ----------------------
def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Try pdfplumber, then PyPDF2, then PyMuPDF (fitz) to read all text from the PDF.
    Install one of them via pip if needed, e.g.: pip install pdfplumber
    """
    text_pages: List[str] = []

    # Try pdfplumber
    try:
        import pdfplumber  # type: ignore
        with pdfplumber.open(pdf_path) as pdf:
            for i in range(len(pdf.pages)):
                text_pages.append(pdf.pages[i].extract_text() or "")
        return "\n\n".join(text_pages)
    except Exception:
        pass

    # Try PyPDF2
    try:
        import PyPDF2  # type: ignore
        with open(pdf_path, "rb") as fp:
            reader = PyPDF2.PdfReader(fp)
            for i in range(len(reader.pages)):
                text_pages.append(reader.pages[i].extract_text() or "")
        return "\n\n".join(text_pages)
    except Exception:
        pass

    # Try PyMuPDF (fitz)
    try:
        import fitz  # type: ignore
        doc = fitz.open(pdf_path)
        for i in range(doc.page_count):
            text_pages.append(doc.load_page(i).get_text() or "")
        return "\n\n".join(text_pages)
    except Exception as e:
        raise RuntimeError(
            "Could not read PDF with pdfplumber, PyPDF2, or PyMuPDF. "
            f"Install one via pip. Details: {e}"
        )

# ---------------------- Morphology helpers ----------------------
def _is_vowel(c: str) -> bool:
    return c.lower() in "aeiou"

def _ends_with_any(w: str, endings) -> bool:
    return any(w.endswith(e) for e in endings)

def _double_final_consonant_for_ing_ed(w: str) -> bool:
    # Double final consonant for CVC words (except w, x, y)
    if len(w) < 3:
        return False
    last = w[-1].lower()
    if last in "wxy":
        return False
    return (not _is_vowel(last)) and _is_vowel(w[-2]) and (not _is_vowel(w[-3]))

def _verb_inflections(base_upper: str) -> set:
    """
    Generate simple English verb inflections (UPPERCASE):
    BASE, 3SG -S/-ES, PAST -ED (or -D if ends with E), -ING with e-dropping and CVC doubling.
    (Irregulars like MAKE->MADE are NOT handled here.)
    """
    b = base_upper
    out = {b}
    low = b.lower()

    # 3rd person singular
    if _ends_with_any(low, ("s", "x", "z", "ch", "sh", "o")):
        out.add(b + "ES")
    elif low.endswith("y") and len(b) > 1 and not _is_vowel(b[-2]):
        out.add(b[:-1] + "IES")
    else:
        out.add(b + "S")

    # PAST
    if low.endswith("e"):
        out.add(b + "D")
    elif _double_final_consonant_for_ing_ed(low):
        out.add(b + b[-1] + "ED")
    else:
        out.add(b + "ED")

    # ING
    if low.endswith("ie"):
        out.add(b[:-2] + "YING")  # TIE->TYING
    elif low.endswith("e") and not low.endswith("ee"):
        out.add(b[:-1] + "ING")   # MAKE->MAKING
    elif _double_final_consonant_for_ing_ed(low):
        out.add(b + b[-1] + "ING")  # STOP->STOPPING
    else:
        out.add(b + "ING")

    return out

def _plural_forms(base_upper: str) -> set:
    """
    Generate simple plural for nouns (UPPERCASE): -S / -ES / -IES.
    """
    b = base_upper
    out = {b}
    low = b.lower()
    if _ends_with_any(low, ("s", "x", "z", "ch", "sh")):
        out.add(b + "ES")             # BOX->BOXES
    elif low.endswith("y") and len(b) > 1 and not _is_vowel(b[-2]):
        out.add(b[:-1] + "IES")       # BODY->BODIES
    else:
        out.add(b + "S")              # VALVE->VALVES
    return out

# ---------------------- Build lexicons ----------------------
HEADWORD_RE = re.compile(r'\n([A-Za-z][A-Za-z0-9\-/ ]{1,})\s*\(([a-zA-Z\. ]+)\)\s')
HEADER_SPLIT_RE = re.compile(r'Word\s+Approved meaning/?\s+STE', flags=re.IGNORECASE)

def build_lexicons_from_pdf(pdf_path: str) -> Tuple[Set[str], Set[str]]:
    """
    Parse the full PDF dictionary tables and return:
      approved_words (official approved + verb inflections + noun plurals),
      forbidden_words (official lowercase headwords only).
    """
    full = extract_text_from_pdf(pdf_path)
    parts = HEADER_SPLIT_RE.split(full)

    approved_words: Set[str] = set()
    forbidden_words: Set[str] = set()

    for sec in parts[1:]:
        for m in HEADWORD_RE.finditer(sec):
            hw = m.group(1).strip()
            pos = m.group(2).strip().lower()

            if not re.search(r'[A-Za-z]', hw):
                continue

            if hw.upper() == hw and hw.lower() != hw:
                # APPROVED headword
                if "v" in pos:
                    approved_words.update(_verb_inflections(hw))
                elif "n" in pos:
                    approved_words.update(_plural_forms(hw))
                else:
                    approved_words.add(hw)
            elif hw.lower() == hw and hw.upper() != hw:
                # FORBIDDEN headword (official only)
                forbidden_words.add(hw)
            else:
                # Mixed case -> skip
                pass

    return approved_words, forbidden_words

def extract_all_caps_words(pdf_path: str) -> Set[str]:
    """
    Sweep the entire PDF text and take all ALL-CAPS tokens (>=3 chars) as an extra allow-list.
    This helps avoid false 'UnapprovedWord' on words that are capitalized throughout.
    """
    text = extract_text_from_pdf(pdf_path)
    words = set()
    for m in re.findall(r"\b[A-Z][A-Z0-9\-]{2,}\b", text):
        if m.isdigit():
            continue
        # Common headings/labels to ignore (tune if needed)
        if m in {
            "WORD","APPROVED","MEANING","ALTERNATIVES","STE","EXAMPLE","NON","PART","SPEECH",
            "PAGE","ISSUE","DICTIONARY","TABLE","FIGURE","APPENDIX","SECTION","NOTE"
        }:
            continue
        words.add(m)
    return words

def ensure_wordlists(approved_path: str, forbidden_path: str, allcaps_path: str, pdf_path: str) -> None:
    """
    If wordlists are missing, attempt to build them from the PDF.
    Produces:
      - approved_path  (official approved + morphology)
      - forbidden_path (official forbidden only)
      - allcaps_path   (ALL-CAPS sweep from full PDF)
    """
    need_build = not (os.path.exists(approved_path) and os.path.exists(forbidden_path) and os.path.exists(allcaps_path))
    if not need_build:
        return

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(
            f"Wordlists not found and PDF not found at:\n{pdf_path}\n"
            "Fix PDF_PATH at the top of this script or place the wordlists next to the script."
        )

    print("Wordlists missing — building from PDF (full). This may take a moment...")
    approved, forbidden = build_lexicons_from_pdf(pdf_path)
    allcaps = extract_all_caps_words(pdf_path)

    with open(approved_path, "w", encoding="utf-8") as f:
        for w in sorted(approved):
            f.write(w + "\n")

    with open(forbidden_path, "w", encoding="utf-8") as f:
        for w in sorted(forbidden):
            f.write(w + "\n")

    with open(allcaps_path, "w", encoding="utf-8") as f:
        for w in sorted(allcaps):
            f.write(w + "\n")

    print(f"Built lexicons.\n  Approved  -> {approved_path} (count: {len(approved)})")
    print(f"  Forbidden -> {forbidden_path} (count: {len(forbidden)})")
    print(f"  ALL-CAPS  -> {allcaps_path} (count: {len(allcaps)})")

# ---------------------- Linter core ----------------------
def load_wordlist(path: str) -> Set[str]:
    with open(path, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def tokenize_words_with_spans(text: str) -> List[Tuple[str, int, int]]:
    toks: List[Tuple[str, int, int]] = []
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9\-\/']*", text):
        toks.append((m.group(0), m.start(), m.end()))
    return toks

def split_sentences_with_spans(text: str) -> List[Tuple[str, int, int]]:
    sents: List[Tuple[str, int, int]] = []
    start = 0
    for m in re.finditer(r"([\.!\?])", text):
        end = m.end()
        chunk = text[start:end].strip()
        if chunk:
            sents.append((chunk, start, end))
        start = end
    if start < len(text):
        chunk = text[start:].strip()
        if chunk:
            sents.append((chunk, start, len(text)))
    return sents

def is_acronym(token: str) -> bool:
    return token.isupper() and sum(c.isalpha() for c in token) >= 2

def lint_text(
    text: str,
    approved_path: str,
    forbidden_path: str,
    allcaps_path: str,
    max_sentence_words: int = 20
) -> List[Dict]:
    # Effective approved = official approved + ALL-CAPS sweep (both lowercased for matching)
    approved = set(w.lower() for w in load_wordlist(approved_path))
    if os.path.exists(allcaps_path):
        approved.update(w.lower() for w in load_wordlist(allcaps_path))

    # Forbidden strictly from official list only
    forbidden = set()
    if os.path.exists(forbidden_path):
        forbidden = set(w.lower() for w in load_wordlist(forbidden_path))

    issues: List[Dict] = []

    # Sentence length
    sentences = split_sentences_with_spans(text)
    for s_idx, (sent, s_start, s_end) in enumerate(sentences):
        words = [t for t, _, _ in tokenize_words_with_spans(sent)]
        if len(words) > max_sentence_words:
            issues.append({
                "type": "SentenceTooLong",
                "message": f"Sentence has {len(words)} words (>{max_sentence_words}).",
                "sentence_index": s_idx,
                "span": (s_start, s_end),
                "suggestion": "Split into shorter sentences (<= 20 words)."
            })

    # Word checks
    for tok, start, end in tokenize_words_with_spans(text):
        low = tok.lower()
        if low.isdigit() or len(low) < 3 or is_acronym(tok):
            continue

        if low in forbidden:
            issues.append({
                "type": "ForbiddenWord",
                "message": f"Forbidden word: '{tok}'",
                "span": (start, end),
                "suggestion": "Replace with an approved alternative per ASD-STE100."
            })
            continue

        if low not in approved:
            issues.append({
                "type": "UnapprovedWord",
                "message": f"Not in approved lexicon: '{tok}'",
                "span": (start, end),
                "suggestion": "Prefer an approved STE word or rephrase."
            })

    # Passive voice heuristic
    for m in re.finditer(r"\b(am|is|are|was|were|be|been|being)\s+\w+ed\b", text, flags=re.IGNORECASE):
        issues.append({
            "type": 'PassiveVoice',
            "message": f"Possible passive: '{text[m.start():m.end()]}'",
            "span": (m.start(), m.end()),
            "suggestion": "Use active voice where possible."
        })

    return issues

# ---------------------- CLI ----------------------
def main():
    p = argparse.ArgumentParser(description="ASD-STE100 (Issue 9) simple linter")
    p.add_argument("--text", type=str, help="Text to lint (direct input).")
    p.add_argument("--file", type=str, help="Path to a text file to lint.")
    p.add_argument("--approved", type=str, default=APPROVED_PATH,
                   help="Approved words list path (default: script folder).")
    p.add_argument("--forbidden", type=str, default=FORBIDDEN_PATH,
                   help="Forbidden words list path (default: script folder).")
    p.add_argument("--allcaps", type=str, default=ALLCAPS_PATH,
                   help="ALL-CAPS words list path (default: script folder).")
    p.add_argument("--report", type=str, help="CSV path for report (optional).")
    p.add_argument("--max-sentence-words", type=int, default=20, help="Max words per sentence.")
    p.add_argument("--pdf", type=str, help="Override PDF path for building lexicons (optional).")
    p.add_argument("--rebuild", action="store_true",
                   help="Force rebuild lexicons from PDF before linting.")
    args = p.parse_args()

    # Pick PDF path (CLI overrides constant)
    pdf_path = args.pdf if args.pdf else PDF_PATH

    # Ensure wordlists exist (or rebuild if asked)
    if args.rebuild or not (os.path.exists(args.approved) and os.path.exists(args.forbidden) and os.path.exists(args.allcaps)):
        ensure_wordlists(args.approved, args.forbidden, args.allcaps, pdf_path)

    if not args.text and not args.file:
        print("Provide --text or --file. (Use --rebuild to regenerate wordlists from the PDF if needed.)")
        print(f"Approved list:  {args.approved}")
        print(f"Forbidden list: {args.forbidden}")
        print(f"ALL-CAPS list:  {args.allcaps}")
        sys.exit(0)

    text = args.text or ""
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()

    issues = lint_text(text, args.approved, args.forbidden, args.allcaps, args.max_sentence_words)

    # Console output
    for i in issues[:200]:
        line = f"[{i['type']}] {i['message']} @ {i.get('span','')}"
        if "sentence_index" in i:
            line += f" (sentence_index={i['sentence_index']})"
        print(line)
        print(f"  suggestion: {i['suggestion']}")

    print(f"\nTotal issues: {len(issues)}")

    # Optional CSV report
    if args.report:
        with open(args.report, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["type","message","span","sentence_index","suggestion"])
            writer.writeheader()
            for i in issues:
                writer.writerow({
                    "type": i.get("type",""),
                    "message": i.get("message",""),
                    "span": i.get("span",""),
                    "sentence_index": i.get("sentence_index",""),
                    "suggestion": i.get("suggestion",""),
                })
        print(f"Report written to {args.report}")

if __name__ == "__main__":
    main()
