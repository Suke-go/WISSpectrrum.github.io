#!/usr/bin/env python3
"""Merge title/authors/PDF URL from WISSProceedings CSV into summary JSON files."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Dict, List, Optional


def read_csv(path: Path) -> List[Dict[str, str]]:
    """Read the proceedings CSV with a tolerant encoding fallback."""
    # Prefer UTF-8 first (recent files), then legacy cp932.
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("all", b"", 0, 1, "Unable to decode CSV with tried encodings")


def split_authors(raw: str) -> List[str]:
    if not raw:
        return []
    parts = re.split(r"[、,]+", raw)
    return [p.strip() for p in parts if p.strip()]


def repair_mojibake(value: str) -> str:
    """
    Try to fix UTF-8 text that was mis-decoded as latin-1 (shows up as 'ã¯...' etc.).
    If conversion fails or yields the same string, return the original.
    """
    if not value:
        return value
    try:
        fixed = value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    if fixed != value and "�" not in fixed:
        return fixed
    return value


def load_mapping(csv_rows: List[Dict[str, str]]) -> Dict[str, Dict[str, object]]:
    """
    Build a mapping from possible stems/ids to metadata.
    Uses id, pdf_url stem, and stem without leading zeros / suffixes.
    """
    mapping: Dict[str, Dict[str, object]] = {}
    for row in csv_rows:
        pdf_url = (row.get("pdf_url") or "").strip()
        title = repair_mojibake((row.get("title") or "").strip())
        authors_raw = repair_mojibake((row.get("authors") or "").strip())
        review_url = (row.get("review_url") or "").strip()
        source_page = (row.get("source_page") or "").strip()
        mp4_url = (row.get("mp4_url") or "").strip()
        raw_id = (row.get("id") or "").strip()
        candidates = []
        if raw_id:
            candidates.append(raw_id)
        if pdf_url:
            candidates.append(Path(pdf_url).stem)

        def add_normalized(value: str) -> None:
            norm = value.lower()
            mapping[norm] = meta
            stripped = norm.lstrip("0")
            if stripped and stripped != norm:
                mapping[stripped] = meta
            if "_" in norm:
                mapping[norm.split("_", 1)[0]] = meta
            hyphen_norm = norm.replace("-", "_")
            if hyphen_norm != norm:
                mapping[hyphen_norm] = meta
                stripped_h = hyphen_norm.lstrip("0")
                if stripped_h and stripped_h != hyphen_norm:
                    mapping[stripped_h] = meta

        if not candidates:
            continue

        meta = {
            "title": title or None,
            "authors": split_authors(authors_raw),
            "pdf_url": pdf_url or None,
            "review_url": review_url or None,
            "source_page": source_page or None,
            "mp4_url": mp4_url or None,
        }
        for cand in candidates:
            add_normalized(cand)
    return mapping


def update_summary(path: Path, meta: Dict[str, object]) -> bool:
    """Apply CSV-derived metadata into a summary JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = False

    title = meta.get("title")
    if title and data.get("title") != title:
        data["title"] = title
        if not data.get("title_en"):
            data["title_en"] = title
        changed = True

    authors: List[str] = meta.get("authors") or []  # type: ignore
    if authors and data.get("authors") != authors:
        data["authors"] = authors
        if not data.get("authors_en"):
            data["authors_en"] = authors
        changed = True

    links = data.get("links") or {}
    if meta.get("pdf_url"):
        if links.get("pdf") != meta["pdf_url"]:
            links["pdf"] = meta["pdf_url"]
            changed = True
    if meta.get("review_url"):
        if links.get("review") != meta["review_url"]:
            links["review"] = meta["review_url"]
            changed = True
    if meta.get("source_page"):
        if links.get("source_page") != meta["source_page"]:
            links["source_page"] = meta["source_page"]
            changed = True
    if meta.get("mp4_url"):
        if links.get("video") != meta["mp4_url"]:
            links["video"] = meta["mp4_url"]
            changed = True
    if changed:
        data["links"] = links
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge title/authors/PDF URL from proceedings CSV into summary JSONs.")
    parser.add_argument("--csv", type=Path, required=True, help="Path to WISSProceedings CSV (e.g., WISSProceedings/wiss2014.csv)")
    parser.add_argument("--summary-dir", type=Path, required=True, help="Directory containing summary JSONs for that year.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing files.")
    args = parser.parse_args()

    rows = read_csv(args.csv)
    mapping = load_mapping(rows)
    if not mapping:
        print("[WARN] No entries parsed from CSV.")
        return 0

    summary_files = sorted(args.summary_dir.glob("*.json"))
    if not summary_files:
        print(f"[WARN] No summary JSONs found in {args.summary_dir}")
        return 0

    updates = 0
    for path in summary_files:
        stem = path.stem.lower()
        parts = [stem]
        digit_groups = re.findall(r"\d+", stem)
        # prefer longer digit groups first (e.g., 06 before 1)
        parts.extend(sorted(set(digit_groups), key=lambda x: (-len(x), x)))
        # append prefix (before underscore) last, so it has lower priority than full numbers
        if "_" in stem:
            parts.append(stem.split("_", 1)[0])
        # also consider stripping leading zeros
        parts.extend([p.lstrip("0") for p in list(parts)])
        # deduplicate while preserving order
        seen = set()
        parts = [p for p in parts if not (p in seen or seen.add(p))]
        meta = None
        for key in parts:
            if key and key in mapping:
                meta = mapping[key]
                break
        if not meta:
            continue
        if args.dry_run:
            # Evaluate changes without writing
            data = json.loads(path.read_text(encoding="utf-8"))
            title = meta.get("title")
            authors: List[str] = meta.get("authors") or []  # type: ignore
            needs_change = False
            if title and data.get("title") != title:
                needs_change = True
            if authors and data.get("authors") != authors:
                needs_change = True
            links = data.get("links") or {}
            for field in ("pdf_url", "review_url", "source_page", "mp4_url"):
                val = meta.get(field)
                mapped_key = {
                    "pdf_url": "pdf",
                    "review_url": "review",
                    "source_page": "source_page",
                    "mp4_url": "video",
                }[field]
                if val and links.get(mapped_key) != val:
                    needs_change = True
            if needs_change:
                updates += 1
                print(f"[DRY] Would update {path.name}")
        else:
            if update_summary(path, meta):
                updates += 1
                print(f"[OK] Updated {path.name}")

    print(f"[INFO] Processed {len(summary_files)} files; updated {updates}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
