# -*- coding: utf-8 -*-
"""
Shortcut runner for merge_led_legal_multi_months.py located in Py Scraper/
Usage: 
  python merge_led_legal_multi_months.py
  python merge_led_legal_multi_months.py --months 2026_09 2026_10
  python merge_led_legal_multi_months.py --months 2026_09 2026_10 2026_11
"""
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_DIR)
_SCRAPER_DIR = os.path.join(_ROOT_DIR, "Py Scraper")

if _SCRAPER_DIR not in sys.path:
    sys.path.insert(0, _SCRAPER_DIR)

from merge_led_legal_multi_months import merge_led_files, argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge LED Legal monthly CSVs and deduplicate repeat auctions")
    parser.add_argument("--months", nargs="+", help="ระบุเดือนที่ต้องการรวม เช่น --months 2026_09 2026_10 หรือ 2026_09 2026_10 2026_11")
    parser.add_argument("--input", nargs="+", help="ระบุไฟล์ CSV อินพุตโดยตรง")
    parser.add_argument("--output", help="ระบุเส้นทางไฟล์ CSV ผลลัพธ์")
    args = parser.parse_args()
    
    merge_led_files(months=args.months, input_files=args.input, output_path=args.output)
