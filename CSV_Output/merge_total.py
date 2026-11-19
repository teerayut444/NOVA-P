# -*- coding: utf-8 -*-
"""
Shortcut runner for merge_all_assets_total.py located in all_assets/
Usage: python merge_total.py
"""
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
_ALL_ASSETS_DIR = os.path.join(_DIR, "all_assets")
if _ALL_ASSETS_DIR not in sys.path:
    sys.path.insert(0, _ALL_ASSETS_DIR)

from merge_all_assets_total import merge_all_monthly_assets

if __name__ == "__main__":
    merge_all_monthly_assets()
