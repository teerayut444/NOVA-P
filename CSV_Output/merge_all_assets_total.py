# -*- coding: utf-8 -*-
"""
Thin wrapper delegating to canonical CSV_Output/all_assets/merge_all_assets_total.py.
Uses float64 precision, preserves NaN locations, and performs atomic Parquet writes.
"""
import argparse
import importlib.util
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
_ALL_ASSETS_DIR = os.path.join(_DIR, "all_assets")
_CANONICAL_PATH = os.path.join(_ALL_ASSETS_DIR, "merge_all_assets_total.py")

if _ALL_ASSETS_DIR not in sys.path:
    sys.path.insert(0, _ALL_ASSETS_DIR)

_spec = importlib.util.spec_from_file_location("_canonical_merge_all_assets_total", _CANONICAL_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

DEFAULT_OUTPUT_FILE = _mod.DEFAULT_OUTPUT_FILE
PREFERRED_COLUMN_ORDER = _mod.PREFERRED_COLUMN_ORDER
standardize_dataframe = _mod.standardize_dataframe
merge_all_monthly_assets = _mod.merge_all_monthly_assets


def merge_monthly_assets(
    csv_output_dir=_ALL_ASSETS_DIR,
    output_file=DEFAULT_OUTPUT_FILE,
    dedup=False,
    add_month_tag=True,
):
    """Backward-compatible wrapper delegating to merge_all_monthly_assets."""
    return merge_all_monthly_assets(
        search_dir=csv_output_dir,
        output_file=output_file,
        dedup=dedup,
        add_month_tag=add_month_tag,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge monthly all_assets.parquet files into all_assets_total.parquet")
    parser.add_argument("-d", "--dir", default=_ALL_ASSETS_DIR)
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT_FILE)
    parser.add_argument("--dedup", action="store_true")
    parser.add_argument("--no-month-tag", action="store_true")
    args = parser.parse_args()
    ok = merge_all_monthly_assets(
        search_dir=args.dir,
        output_file=args.output,
        dedup=args.dedup,
        add_month_tag=not args.no_month_tag,
    )
    if not ok:
        sys.exit(1)
