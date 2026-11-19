# -*- coding: utf-8 -*-
"""
Shortcut runner for canonical Py Scraper/merge_csv_monthly.py.
Usage: python merge.py
"""
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR) if os.path.basename(_DIR).lower() == "csv_output" else _DIR
_SCRAPER_DIR = os.path.join(_ROOT, "Py Scraper")

for _p in [_ROOT, _SCRAPER_DIR]:
    if os.path.exists(_p):
        if _p in sys.path:
            sys.path.remove(_p)
        sys.path.insert(0, _p)

from merge_csv_monthly import merge_monthly_csv

if __name__ == "__main__":
    no_pq = any(a.lower() in ["--no-parquet", "-no-parquet", "no-parquet"] for a in sys.argv)
    merge_monthly_csv(generate_parquet=not no_pq)
