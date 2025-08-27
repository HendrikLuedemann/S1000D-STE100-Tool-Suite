#!/usr/bin/env python3
"""
validate_xml_against_xsd.py

Validate a single XML file against a chosen XSD.

Usage:
  # 1) Directly specify both files
  python validate_xml_against_xsd.py --xml /path/to/file.xml --xsd /path/to/schema.xsd

  # 2) Let the tool list all XSDs in a folder and choose interactively
  python validate_xml_against_xsd.py --xml /path/to/file.xml --xsd-dir /path/to/xsds
"""
import argparse
import sys
from pathlib import Path
from typing import List, Tuple
from lxml import etree


def index_xsds(xsd_dir: Path) -> List[Tuple[str, Path, str, List[str]]]:
    """
    Return a list of (display_name, path, targetNamespace, global_elements[])
    for each *.xsd file in xsd_dir.
    """
    out: List[Tuple[str, Path, str, List[str]]] = []
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)
    for p in sorted(xsd_dir.glob("*.xsd")):
        tns = ""
        elems: List[str] = []
        try:
            doc = etree.parse(str(p), parser)
            root = doc.getroot()
            tns = root.get("targetNamespace", "")
            XS = "http://www.w3.org/2001/XMLSchema"
            for el in root.findall(f"{{{XS}}}element"):
                name = el.get("name")
                if name:
                    elems.append(name)
        except Exception as e:
            tns = f"PARSE ERROR: {e}"
        out.append((p.name, p, tns, elems))
    return out


def choose_schema_interactive(xsd_dir: Path) -> Path:
    entries = index_xsds(xsd_dir)
    if not entries:
        print(f"ERROR: No .xsd files found in {xsd_dir}", file=sys.stderr)
        sys.exit(2)

    print("\nDiscovered XSDs:\n")
    for i, (name, path, tns, elems) in enumerate(entries, start=1):
        elems_preview = ", ".join(elems[:8]) + ("..." if len(elems) > 8 else "")
        tns_preview = tns if tns else "(no targetNamespace)"
        print(f"[{i:2}] {name}")
        print(f"     path : {path}")
        print(f"     tns  : {tns_preview}")
        if elems_preview:
            print(f"     elems: {elems_preview}")
        print()

    while True:
        choice = input(f"Select schema [1-{len(entries)}] (or 'q' to quit): ").strip().lower()
        if choice in ("q", "quit", "exit"):
            print("Aborted.")
            sys.exit(0)
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(entries):
                return entries[idx - 1][1]
        print("Invalid choice. Try again.")


def resolve_xsd_path(xsd_arg: str, xsd_dir: Path | None) -> Path:
    p = Path(xsd_arg)
    if p.exists():
        return p.resolve()
    if xsd_dir:
        cand = (xsd_dir / xsd_arg)
        if cand.exists():
            return cand.resolve()
    print(f"ERROR: XSD not found: {xsd_arg}", file=sys.stderr)
    if xsd_dir:
        print(f"       (looked in {xsd_dir})", file=sys.stderr)
    sys.exit(2)


def validate(xml_path: Path, xsd_path: Path) -> int:
    try:
        xsd_doc = etree.parse(str(xsd_path))
        schema = etree.XMLSchema(xsd_doc)
    except Exception as e:
        print(f"ERROR: Failed to load XSD '{xsd_path}': {e}", file=sys.stderr)
        return 2

    try:
        doc = etree.parse(str(xml_path))
    except Exception as e:
        print(f"[FAIL] Parse error in XML '{xml_path}': {e}")
        return 1

    try:
        schema.assertValid(doc)
        print(f"[ OK ] {xml_path} is valid against {xsd_path.name}")
        return 0
    except etree.DocumentInvalid:
        errors = schema.error_log
        print(f"[FAIL] Validation failed for {xml_path} against {xsd_path.name}")
        for i, err in enumerate(errors):
            if i > 9:
                print(f"... and {len(errors)-10} more error(s)")
                break
            print(f"Line {err.line}, Col {err.column}: {err.message}")
        return 1
    except Exception as e:
        print(f"[FAIL] Validation error: {e}")
        return 1


def main():
    ap = argparse.ArgumentParser(
        description="Validate a single XML file against a chosen XSD (direct or interactive)."
    )
    ap.add_argument("--xml", required=True, type=Path, help="Path to the XML file to validate.")
    ap.add_argument("--xsd", type=str, help="Path or filename of the XSD to use.")
    ap.add_argument("--xsd-dir", type=Path,
                    help="Directory containing XSDs. Required if --xsd is a bare filename or omitted for interactive choice.")
    args = ap.parse_args()

    xml_path = args.xml.resolve()
    if not xml_path.exists():
        print(f"ERROR: XML not found: {xml_path}", file=sys.stderr)
        sys.exit(2)

    # Determine XSD path
    if args.xsd:
        if not args.xsd_dir and not Path(args.xsd).exists() and Path(args.xsd).name == args.xsd:
            print("Note: --xsd looks like a filename; supply --xsd-dir so I can find it there.", file=sys.stderr)
        xsd_dir = args.xsd_dir.resolve() if args.xsd_dir else None
        xsd_path = resolve_xsd_path(args.xsd, xsd_dir)
    else:
        if not args.xsd_dir:
            print("ERROR: Either provide --xsd, or provide --xsd-dir to choose interactively.", file=sys.stderr)
            sys.exit(2)
        xsd_dir = args.xsd_dir.resolve()
        if not xsd_dir.exists():
            print(f"ERROR: XSD dir does not exist: {xsd_dir}", file=sys.stderr)
            sys.exit(2)
        xsd_path = choose_schema_interactive(xsd_dir)

    rc = validate(xml_path, xsd_path)
    sys.exit(rc)


if __name__ == "__main__":
    main()
