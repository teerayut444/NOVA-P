# -*- coding: utf-8 -*-
"""
Thin wrapper delegating to canonical Py Scraper/merge_csv_monthly.py.
Kept for backward compatibility with existing batch scripts and callers.
"""
import importlib.util
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR) if os.path.basename(_DIR).lower() == "csv_output" else _DIR
_SCRAPER_DIR = os.path.join(_ROOT, "Py Scraper")

for _p in [_ROOT, _SCRAPER_DIR]:
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

_CANONICAL_PATH = os.path.join(_SCRAPER_DIR, "merge_csv_monthly.py")
_spec = importlib.util.spec_from_file_location("_canonical_merge_csv_monthly", _CANONICAL_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

PROPERTY_TYPE_MAPPING = _mod.PROPERTY_TYPE_MAPPING
COLUMNS = _mod.COLUMNS
parse_rai_ngan_wah_robust = _mod.parse_rai_ngan_wah_robust
convert_to_rai_ngan_wah = _mod.convert_to_rai_ngan_wah
resolve_mixed_property_types = _mod.resolve_mixed_property_types
merge_monthly_csv = _mod.merge_monthly_csv

if __name__ == "__main__":
    no_pq = any(a.lower() in ["--no-parquet", "-no-parquet", "no-parquet"] for a in sys.argv)
    ok = merge_monthly_csv(generate_parquet=not no_pq)
    if not ok:
        sys.exit(1)
