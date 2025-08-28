import argparse
import math
import os
from pathlib import Path
from typing import Iterable, Tuple, Optional, List

from transformers import AutoTokenizer
from pypdf import PdfReader


def load_tokenizer(model_name: str):
    """
    Load the Qwen tokenizer (or any HF tokenizer) by model name.
    """
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    except Exception as e:
        raise RuntimeError(
            f"Failed to load tokenizer '{model_name}'. "
            f"Make sure the model exists and you have internet access if not cached.\nError: {e}"
        )
    return tokenizer


def iter_folder_files(folder: Path) -> Iterable[Path]:
    """
    Yield all .txt and .pdf files recursively from a folder.
    """
    for p in folder.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".txt", ".pdf"}:
            yield p


def read_text_file(path: Path, encoding_candidates: Optional[List[str]] = None) -> str:
    """
    Read text from a .txt file trying a few encodings.
    """
    if encoding_candidates is None:
        encoding_candidates = ["utf-8", "utf-16", "latin-1"]

    last_err = None
    for enc in encoding_candidates:
        try:
            return path.read_text(encoding=enc, errors="strict")
        except Exception as e:
            last_err = e
    # fallback with replacement to avoid crash
    return path.read_text(encoding="utf-8", errors="replace")


def read_pdf_text(path: Path) -> str:
    """
    Extract text from a PDF using pypdf.
    Note: Scanned/image PDFs won’t yield text (OCR required).
    """
    try:
        reader = PdfReader(str(path))
    except Exception as e:
        raise RuntimeError(f"Failed to open PDF '{path}': {e}")

    texts = []
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
        except Exception as e:
            raise RuntimeError(f"Failed to extract text from page {i+1} in '{path}': {e}")
        texts.append(t)
    return "\n".join(texts)


def read_any(path: Path) -> str:
    if path.suffix.lower() == ".txt":
        return read_text_file(path)
    elif path.suffix.lower() == ".pdf":
        return read_pdf_text(path)
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")


def count_tokens_str(text: str, tokenizer) -> int:
    """
    Count tokens for a given text using the provided tokenizer.
    NOTE: This uses tokenizer.encode(text) as in your original script,
    which may include special tokens depending on the tokenizer.
    """
    return len(tokenizer.encode(text))


def count_tokens_file(path: Path, tokenizer) -> Tuple[Path, int]:
    text = read_any(path)
    return path, count_tokens_str(text, tokenizer)


def parse_margin(value: Optional[str]) -> float:
    """
    Parse --margin into a multiplier fraction.
    Accepts '5', '5%', '0.05', '10', etc.
    Returns a float like 0.05 for 5%.
    """
    if not value:
        return 0.0
    s = value.strip()
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        v = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid margin value: {value}")
    # If user passed 5 -> 5%, convert to 0.05. If 0.05, keep it.
    if v > 1.0:
        v = v / 100.0
    if v < -0.5 or v > 1.0:
        raise argparse.ArgumentTypeError("Margin must be between -50% and 100%.")
    return v


def apply_margin(n: int, margin: float) -> int:
    """
    Apply a percentage margin and ceil to avoid underestimation.
    """
    if margin == 0.0:
        return n
    return int(math.ceil(n * (1.0 + margin)))


def main():
    parser = argparse.ArgumentParser(
        description="Count tokens with a Qwen-compatible (or any HF) tokenizer from text/files/folders.",
    )
    parser.add_argument("--text", type=str, help="Raw text to count tokens for.")
    parser.add_argument("--file", type=str, help="Path to a single .txt or .pdf file.")
    parser.add_argument("--folder", type=str, help="Path to a folder; counts all .txt and .pdf files recursively.")
    parser.add_argument(
        "--tokenizer",
        type=str,
        default="Qwen/Qwen3-235B-A22B-Instruct-2507",
        help="Hugging Face tokenizer id (default: Qwen/Qwen3-235B-A22B-Instruct-2507)."
    )
    parser.add_argument(
        "--margin",
        type=parse_margin,
        default=0.0,
        help="Optional percentage margin to approximate other models' counts. "
             "Examples: --margin 5  (5%), --margin 10%%, --margin 0.05."
    )
    args = parser.parse_args()

    # Load tokenizer
    tokenizer = load_tokenizer(args.tokenizer)

    grand_total = 0
    any_output = False
    margin = args.margin

    def print_with_margin(prefix: str, path_or_text: str, count: int):
        if margin != 0.0:
            adj = apply_margin(count, margin)
            pct = f"{margin*100:.2f}%"
            print(f"{prefix} {path_or_text} -> {count} tokens (approx +{pct}: {adj})")
        else:
            print(f"{prefix} {path_or_text} -> {count} tokens")

    if args.text is not None:
        n = count_tokens_str(args.text, tokenizer)
        print_with_margin("[TEXT]", "", n)
        grand_total += n
        any_output = True

    if args.file:
        p = Path(args.file)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {p}")
        if p.suffix.lower() not in {".txt", ".pdf"}:
            raise ValueError("Only .txt and .pdf are supported for --file.")
        path, n = count_tokens_file(p, tokenizer)
        print_with_margin("[FILE]", str(path), n)
        grand_total += n
        any_output = True

    if args.folder:
        folder = Path(args.folder)
        if not folder.exists() or not folder.is_dir():
            raise NotADirectoryError(f"Not a folder: {folder}")
        counts = []
        for p in iter_folder_files(folder):
            try:
                path, n = count_tokens_file(p, tokenizer)
                counts.append((path, n))
                grand_total += n
            except Exception as e:
                print(f"[WARN] Skipped '{p}': {e}")

        # Sort by path for stable output
        counts.sort(key=lambda x: str(x[0]).lower())
        for path, n in counts:
            print_with_margin("[FOLDER]", str(path), n)
        any_output = True

    if not any_output:
        parser.error("Please provide at least one of --text, --file, or --folder.")

    print("-" * 40)
    if margin != 0.0:
        approx_total = apply_margin(grand_total, margin)
        print(f"TOTAL tokens: {grand_total}  (approx +{margin*100:.2f}%: {approx_total})")
    else:
        print(f"TOTAL tokens: {grand_total}")


if __name__ == "__main__":
    main()
