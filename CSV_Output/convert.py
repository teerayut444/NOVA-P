# -*- coding: utf-8 -*-
"""
Shortcut runner for canonical Root convert_csv_to_parquet.py.
Usage: python convert.py
"""
import argparse
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR) if os.path.basename(_DIR).lower() == "csv_output" else _DIR

for _p in [os.path.join(_ROOT, "Py Scraper"), _ROOT]:
    if os.path.exists(_p):
        if _p in sys.path:
            sys.path.remove(_p)
        sys.path.insert(0, _p)

from convert_csv_to_parquet import convert_csv_to_parquet

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert merged monthly CSV to canonical float64 Parquet")
    parser.add_argument("-i", "--input", default=None)
    parser.add_argument("-o", "--output", default=os.path.join(_ROOT, "all_assets.parquet"))
    parser.add_argument("--keep-all", action="store_true")
    args = parser.parse_args()
    convert_csv_to_parquet(
        input_path=args.input,
        output_path=args.output,
        exclude_unwanted=not args.keep_all,
    )
