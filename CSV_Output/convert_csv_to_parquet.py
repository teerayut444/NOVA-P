# -*- coding: utf-8 -*-
"""
Thin wrapper delegating to canonical Root/convert_csv_to_parquet.py.
Kept for backward compatibility with existing batch scripts and workflows.
"""
import argparse
import importlib.util
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR) if os.path.basename(_DIR).lower() == "csv_output" else _DIR

for _p in [os.path.join(_ROOT, "Py Scraper"), _ROOT]:
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

_CANONICAL_PATH = os.path.join(_ROOT, "convert_csv_to_parquet.py")
_spec = importlib.util.spec_from_file_location("_canonical_convert_csv_to_parquet", _CANONICAL_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

PROPERTY_TYPE_MAPPING = _mod.PROPERTY_TYPE_MAPPING
EXCLUDED_COMPANIES = _mod.EXCLUDED_COMPANIES
SALE_TYPE_MAPPING = _mod.SALE_TYPE_MAPPING
parse_land_sqwah = _mod.parse_land_sqwah
read_csv_safely = _mod.read_csv_safely
optimize_and_clean_dataframe = _mod.optimize_and_clean_dataframe
find_best_input_csv = _mod.find_best_input_csv
convert_csv_to_parquet = _mod.convert_csv_to_parquet

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert merged CSV to canonical float64 Parquet")
    parser.add_argument("-i", "--input", default=None)
    parser.add_argument("-o", "--output", default=os.path.join(_ROOT, "all_assets.parquet"))
    parser.add_argument("--keep-all", action="store_true")
    args = parser.parse_args()
    ok = convert_csv_to_parquet(
        input_path=args.input,
        output_path=args.output,
        exclude_unwanted=not args.keep_all,
    )
    if not ok:
        sys.exit(1)
