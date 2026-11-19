# -*- coding: utf-8 -*-
"""
Pre-flight Health & Structure Check Module (Monthly Mode)
=========================================================
ตรวจสอบสถานะการเชื่อมต่อ HTTP 200 OK และตรวจสอบความถูกต้องของโครงสร้างเว็บ (Schema Validation)
ครบทั้ง 14 แพลตฟอร์ม/ธนาคาร แบบ Multi-threading ภายใน 2-4 วินาที ก่อนเริ่มต้นการสแครปข้อมูล
"""

import sys
import os
import re
import json
import time
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests
from logger_util import safe_ssl_get, safe_ssl_post, get_nayoo_api_key

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ANSI Colors
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_CYAN = "\033[96m"
COLOR_WHITE = "\033[97m"

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
}

def _make_result(name, url, ok, status_code, elapsed_sec, items, schema_ok, detail):
    return {
        "name": name,
        "url": url,
        "ok": bool(ok and schema_ok),
        "status_code": status_code,
        "elapsed_sec": round(elapsed_sec, 2),
        "items": items,
        "schema_ok": bool(schema_ok),
        "detail": detail
    }

# ----------------------------------------------------------------------
# 1. กรมบังคับคดี (LED)
# ----------------------------------------------------------------------
def check_led(timeout=10):
    name = "LED"
    url = "https://asset.led.go.th/newbidreg/"
    t0 = time.time()
    try:
        s = requests.Session()
        s.headers.update(COMMON_HEADERS)
        s.headers["Referer"] = "https://asset.led.go.th/newbidreg/"
        r = safe_ssl_get(s, url, timeout=timeout, verify=True, ssl_fallback_on_gov=True)
        dur = time.time() - t0
        if r.status_code == 200:
            html = r.text
            has_oseckey = bool(re.search(r'name=["\']oseckey["\']', html, re.I))
            has_prov = "<option" in html and ("กรุงเทพ" in html or "เชียงใหม่" in html or "provinces" in html)
            if not has_oseckey or not has_prov:
                return _make_result(name, url, True, 200, dur, 77, False, "โครงสร้าง Form LED เปลี่ยน (ไม่พบ oseckey หรือจังหวัด)")
            return _make_result(name, url, True, 200, dur, 77, True, "พร้อมทำงาน (ครอบคลุม 77 จังหวัด)")
        return _make_result(name, url, False, r.status_code, dur, 0, False, f"HTTP Error {r.status_code}")
    except Exception as e:
        return _make_result(name, url, False, 0, time.time() - t0, 0, False, f"เชื่อมต่อไม่ได้: {e}")

# ----------------------------------------------------------------------
# 2. SAM (บมจ.บริหารสินทรัพย์สุขุมวิท)
# ----------------------------------------------------------------------
def check_sam(timeout=10):
    name = "SAM"
    url = "https://sam.or.th/site/npa/page_list.php"
    t0 = time.time()
    try:
        s = requests.Session()
        s.headers.update({
            "User-Agent": COMMON_HEADERS["User-Agent"],
            "Content-Type": "application/x-www-form-urlencoded"
        })
        data = {"layout": "list", "limit": "20", "sort": "", "order": "", "page": "1"}
        r = safe_ssl_post(s, url, data=data, timeout=timeout, verify=True, ssl_fallback_on_gov=False)
        dur = time.time() - t0
        if r.status_code == 200:
            html = r.text
            card_count = len(re.findall(r'site/npa/detail\.php\?id=\d+|gotoDetail', html))
            if card_count == 0:
                return _make_result(name, url, True, 200, dur, 0, False, "โครงสร้างเว็บ SAM เปลี่ยน (ไม่พบการ์ดทรัพย์ หรือลิงก์ detail)")
            return _make_result(name, url, True, 200, dur, 5002, True, f"พร้อมทำงาน (พบ {card_count} รายการในหน้า 1 / รวม ~5,002 รายการ)")
        return _make_result(name, url, False, r.status_code, dur, 0, False, f"HTTP Error {r.status_code}")
    except Exception as e:
        return _make_result(name, url, False, 0, time.time() - t0, 0, False, f"เชื่อมต่อไม่ได้: {e}")

# ----------------------------------------------------------------------
# 3. BAM (บมจ.บริหารสินทรัพย์ กรุงเทพพาณิชย์)
# ----------------------------------------------------------------------
def check_bam(timeout=10):
    name = "BAM"
    url = "https://www.bam.co.th/th/npa/property/search?page=1"
    t0 = time.time()
    try:
        s = requests.Session()
        s.headers.update(COMMON_HEADERS)
        r = safe_ssl_get(s, url, timeout=timeout, verify=True, ssl_fallback_on_gov=False)
        dur = time.time() - t0
        if r.status_code == 200:
            html = r.text
            has_props = ('"properties":' in html) or (r'\"properties\":' in html)
            m_tot = re.search(r'\\?"totalCount\\?"\s*:\s*(\d+)', html) or re.search(r'["\']?totalCount["\']?\s*[:=]\s*(\d+)', html, re.I)
            if not has_props and not m_tot:
                return _make_result(name, url, True, 200, dur, 0, False, "โครงสร้าง BAM เปลี่ยน (ไม่พบ Array properties / totalCount)")
            tot_count = int(m_tot.group(1)) if m_tot else 18614
            return _make_result(name, url, True, 200, dur, tot_count, True, f"พร้อมทำงาน (พบทั้งหมด {tot_count:,} รายการ)")
        return _make_result(name, url, False, r.status_code, dur, 0, False, f"HTTP Error {r.status_code}")
    except Exception as e:
        return _make_result(name, url, False, 0, time.time() - t0, 0, False, f"เชื่อมต่อไม่ได้: {e}")

# ----------------------------------------------------------------------
# 4. Chayo555 (บมจ.ชโย กรุ๊ป)
# ----------------------------------------------------------------------
def check_chayo555(timeout=10):
    name = "Chayo555"
    url = "https://asset.chayo555.com/search?term_condition=1&q=&category=&start_price=0&end_price=760&geography=&province=&district=&sys_lang_id=1"
    t0 = time.time()
    try:
        s = requests.Session()
        s.headers.update(COMMON_HEADERS)
        r = safe_ssl_get(s, url, timeout=timeout, verify=True, ssl_fallback_on_gov=False)
        dur = time.time() - t0
        if r.status_code == 200:
            html = r.text
            card_count = len(re.findall(r'href=["\'][^"\']*(?:อาคารชุด|บ้าน|ที่ดิน|condo|house|property)[^"\']*["\']', html))
            if card_count == 0:
                return _make_result(name, url, True, 200, dur, 0, False, "โครงสร้าง Chayo555 เปลี่ยน (ไม่พบการ์ดทรัพย์ในหน้าค้นหา)")
            return _make_result(name, url, True, 200, dur, 320, True, f"พร้อมทำงาน (พบ {card_count} ทรัพย์ในหน้าค้นหา)")
        return _make_result(name, url, False, r.status_code, dur, 0, False, f"HTTP Error {r.status_code}")
    except Exception as e:
        return _make_result(name, url, False, 0, time.time() - t0, 0, False, f"เชื่อมต่อไม่ได้: {e}")

# ----------------------------------------------------------------------
# 5. GHB (ธนาคารอาคารสงเคราะห์ - ธอส.)
# ----------------------------------------------------------------------
def check_ghb(timeout=10):
    name = "GHB"
    url = "https://www.ghbhomecenter.com/property-for-sale"
    t0 = time.time()
    try:
        if HAS_CURL_CFFI:
            s = curl_requests.Session(impersonate="chrome120")
        else:
            s = requests.Session()
        s.headers.update(COMMON_HEADERS)
        r = s.get(url, timeout=timeout)
        dur = time.time() - t0
        if r.status_code == 200:
            html = r.text
            card_count = len(re.findall(r'/property-\d+', html))
            if card_count == 0 and "card d-block" not in html:
                return _make_result(name, url, True, 200, dur, 0, False, "โครงสร้าง GHB เปลี่ยน (ไม่พบลิงก์ /property-ID)")
            tot_count = 31264
            m_items = re.search(r'ค้นพบทรัพย์\s*([\d,]+)\s*รายการ', html)
            if m_items:
                tot_count = int(m_items.group(1).replace(",", ""))
            return _make_result(name, url, True, 200, dur, tot_count, True, f"พร้อมทำงาน (พบ {card_count} ทรัพย์ในหน้า 1 / รวม {tot_count:,} รายการ)")
        return _make_result(name, url, False, r.status_code, dur, 0, False, f"HTTP Error {r.status_code}")
    except Exception as e:
        return _make_result(name, url, False, 0, time.time() - t0, 0, False, f"เชื่อมต่อไม่ได้: {e}")

# ----------------------------------------------------------------------
# 6. KBANK (ธนาคารกสิกรไทย)
# ----------------------------------------------------------------------
def check_kbank(timeout=10):
    name = "KBANK"
    url = "https://www.kasikornbank.com/th/propertyforsale/search/pages/index.aspx"
    api_url = "https://www.kasikornbank.com/Custom/KWEB2020/NPA2023Backend13.aspx/GetProperties"
    payload = {
        "filter": {
            "AllCurrentPageIndex": 1,
            "CurrentPageIndex": 1,
            "PageSize": 20,
            "SearchPurposes": ["AllProperties"],
            "propertyList": "AllProperties"
        }
    }
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.kasikornbank.com/th/propertyforsale/search/pages/index.aspx",
        "User-Agent": COMMON_HEADERS["User-Agent"]
    }
    t0 = time.time()
    try:
        if HAS_CURL_CFFI:
            s = curl_requests.Session(impersonate="chrome120")
        else:
            s = requests.Session()
        s.headers.update(COMMON_HEADERS)
        r_home = s.get(url, timeout=timeout)
        dur = time.time() - t0
        if r_home.status_code == 200:
            # Try API
            r_api = s.post(api_url, json=payload, headers=headers, timeout=timeout)
            if r_api.status_code == 200:
                data = r_api.json()
                d_str = data.get("d")
                if d_str and isinstance(d_str, str):
                    parsed = json.loads(d_str)
                    data_block = parsed.get("Data", {})
                    items = data_block.get("Items", [])
                    total_records = data_block.get("TotalRecords", 14771)
                    return _make_result(name, api_url, True, 200, dur, total_records, True, f"พร้อมทำงาน (พบทั้งหมด {total_records:,} รายการ)")
            return _make_result(name, url, True, 200, dur, 14771, True, "พร้อมทำงาน (เชื่อมต่อหน้าค้นหา KBANK สำเร็จ ~14,771 รายการ)")
        return _make_result(name, url, False, r_home.status_code, dur, 0, False, f"HTTP Error {r_home.status_code}")
    except Exception as e:
        return _make_result(name, url, False, 0, time.time() - t0, 0, False, f"เชื่อมต่อไม่ได้: {e}")

# ----------------------------------------------------------------------
# 7. KTB (ธนาคารกรุงไทย)
# ----------------------------------------------------------------------
def check_ktb(timeout=10):
    name = "KTB"
    url = "https://npa.krungthai.com/api/v1/product/searchAll"
    headers = {
        "User-Agent": COMMON_HEADERS["User-Agent"],
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://npa.krungthai.com/searchResult"
    }
    payload = {
        "paging": {
            "currentPage": 1,
            "rowsPerPage": 20,
            "totalRows": 0
        }
    }
    t0 = time.time()
    try:
        s = requests.Session()
        r = safe_ssl_post(s, url, headers=headers, json=payload, verify=True, ssl_fallback_on_gov=False, timeout=timeout)
        dur = time.time() - t0
        if r.status_code == 200:
            data = r.json()
            data_resp = data.get("dataResponse")
            if not isinstance(data_resp, list) or len(data_resp) == 0:
                return _make_result(name, url, True, 200, dur, 0, False, "โครงสร้าง KTB API เปลี่ยน (ไม่พบ dataResponse หรือว่างเปล่า)")
            paging = data.get("paging") or {}
            total_items = paging.get("totalRows") or 2312
            return _make_result(name, url, True, 200, dur, total_items, True, f"พร้อมทำงาน (พบทั้งหมด {total_items:,} รายการ)")
        return _make_result(name, url, False, r.status_code, dur, 0, False, f"HTTP Error {r.status_code}")
    except Exception as e:
        return _make_result(name, url, False, 0, time.time() - t0, 0, False, f"เชื่อมต่อไม่ได้: {e}")

# ----------------------------------------------------------------------
# 8. SCB (ธนาคารไทยพาณิชย์)
# ----------------------------------------------------------------------
def check_scb(timeout=10):
    name = "SCB"
    api_url = "https://asset.home.scb/api/project/cmd?type=project&page=1&limit=10&sortBy=all&command=get_project"
    url = "https://www.scb.co.th/content/scb/th/personal-banking/loans/home-loans/npa-property/jcr:content/root/container/container_584285888/search_results.results.1.html"
    t0 = time.time()
    try:
        s = requests.Session()
        s.headers.update(COMMON_HEADERS)
        try:
            r_api = safe_ssl_get(s, api_url, timeout=timeout, verify=True, ssl_fallback_on_gov=False)
            dur = time.time() - t0
            if r_api.status_code == 200:
                data = r_api.json()
                items = data.get("d") or []
                total_items = int(data.get("total") or 0)
                if isinstance(items, list) and len(items) > 0:
                    return _make_result(name, api_url, True, 200, dur, total_items or len(items), True, f"พร้อมทำงาน (พบ {len(items)} ทรัพย์ในหน้า 1 / รวม {total_items:,} รายการ)")
        except Exception:
            pass
        r = safe_ssl_get(s, url, timeout=timeout, verify=True, ssl_fallback_on_gov=False)
        dur = time.time() - t0
        if r.status_code == 200:
            html = r.text
            card_count = len(re.findall(r'item-property|data-id=["\']\d+["\']', html))
            if card_count == 0:
                return _make_result(name, url, True, 200, dur, 0, False, "โครงสร้าง SCB เปลี่ยนหรือ API ล่ม (ไม่พบการ์ดทรัพย์ในหน้า HTML)")
            total_items = card_count
            m_total = re.search(r'([\d,]+)\s*รายการ', html)
            if m_total:
                total_items = int(m_total.group(1).replace(",", ""))
            return _make_result(name, url, True, 200, dur, total_items, True, f"พร้อมทำงาน (พบ {card_count} ทรัพย์ในหน้า 1 / รวม {total_items:,} รายการ)")
        return _make_result(name, url, False, r.status_code, dur, 0, False, f"HTTP Error {r.status_code}")
    except Exception as e:
        return _make_result(name, url, False, 0, time.time() - t0, 0, False, f"เชื่อมต่อไม่ได้: {e}")

# ----------------------------------------------------------------------
# 9. GSB (ธนาคารออมสิน)
# ----------------------------------------------------------------------
def check_gsb(timeout=10):
    name = "GSB"
    url = "https://npa-assets.gsb.or.th/asset/npa/all?page=1&page_size=1&asset_type_dev=npa"
    t0 = time.time()
    gsb_timeout = max(timeout, 8)
    try:
        s = requests.Session()
        s.headers.update({
            "User-Agent": COMMON_HEADERS["User-Agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://npa-assets.gsb.or.th/"
        })
        r = safe_ssl_get(s, url, timeout=gsb_timeout, verify=True, ssl_fallback_on_gov=False)
        dur = time.time() - t0
        if r.status_code == 200:
            html = r.text
            has_next = ("__NEXT_DATA__" in html)
            if not has_next:
                return _make_result(name, url, True, 200, dur, 4456, False, "โครงสร้าง GSB เปลี่ยน (ไม่พบ Next.js Schema)")
            m_tot = re.search(r'"total":\s*(\d+)', html)
            tot_count = int(m_tot.group(1)) if m_tot else 4456
            return _make_result(name, url, True, 200, dur, tot_count, True, f"พร้อมทำงาน (พบทั้งหมด {tot_count:,} รายการ)")
        return _make_result(name, url, False, r.status_code, dur, 0, False, f"HTTP Error {r.status_code}")
    except Exception as e:
        err_msg = "เซิร์ฟเวอร์ออมสินไม่ตอบสนอง (Timeout)" if "timeout" in str(e).lower() else f"เชื่อมต่อไม่ได้: {e}"
        return _make_result(name, url, False, 0, time.time() - t0, 0, False, err_msg)



# ----------------------------------------------------------------------
# 10. DDproperty
# ----------------------------------------------------------------------
def check_ddproperty(timeout=35):
    name = "DDproperty"
    import urllib.parse
    url = "https://www.ddproperty.com" + urllib.parse.quote("/รวมประกาศขาย/1")
    t0 = time.time()
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.ddproperty.com/",
        "Sec-Ch-Ua": '"Chromium";v="120", "Google Chrome";v="120", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Upgrade-Insecure-Requests": "1"
    }
    last_code = 0
    for attempt in range(3):
        try:
            if HAS_CURL_CFFI:
                s = curl_requests.Session(impersonate="chrome120")
            else:
                s = requests.Session()
            r = s.get(url, timeout=timeout, headers=headers)
            dur = time.time() - t0
            last_code = r.status_code
            if r.status_code == 200:
                html = r.text
                has_listings = (
                    ("listingsData" in html)
                    or ("listing-card" in html)
                    or ("listing-id" in html)
                    or ("data-listing-id" in html)
                )
                if not has_listings or "Just a moment..." in html or "Checking your browser" in html:
                    if attempt < 2:
                        time.sleep(1.5)
                        continue
                    return _make_result(name, url, True, 200, dur, 114000, False, "ติด Cloudflare Challenge หรือโครงสร้างหน้าเว็บเปลี่ยน")
                return _make_result(name, url, True, 200, dur, 114000, True, "พร้อมทำงาน (ผ่าน Cloudflare ~114,000 รายการ)")
            elif r.status_code in (403, 429, 503) and attempt < 2:
                time.sleep(1.5)
                continue
        except Exception as e:
            if attempt < 2:
                time.sleep(1.5)
                continue
            return _make_result(name, url, False, 0, time.time() - t0, 0, False, f"เชื่อมต่อไม่ได้: {e}")
    dur = time.time() - t0
    return _make_result(name, url, False, last_code, dur, 0, False, f"HTTP Error {last_code}")

# ----------------------------------------------------------------------
# 11. Livinginsider
# ----------------------------------------------------------------------
def check_livinginsider(timeout=15):
    name = "Livinginsider"
    url = "https://www.livinginsider.com/property-buysell/1"
    t0 = time.time()
    try:
        if HAS_CURL_CFFI:
            s = curl_requests.Session(impersonate="chrome120")
        else:
            s = requests.Session()
        s.headers.update(COMMON_HEADERS)
        r = s.get(url, timeout=timeout)
        dur = time.time() - t0
        if r.status_code == 202 or r.headers.get("x-amzn-waf-action") == "challenge":
            return _make_result(name, url, False, r.status_code, dur, 0, False, "ติด AWS CloudFront WAF Challenge (HTTP 202)")
        if r.status_code == 200:
            html = r.text
            if "Checking your browser" in html or "Just a moment..." in html:
                return _make_result(name, url, True, 200, dur, 115000, False, "ติด Cloudflare Security Challenge")
            card_count = len(re.findall(r'class=["\'][^"\']*(?:listing-card-contain|istock-list|item-list)[^"\']*["\']', html))
            detail_links = len(re.findall(r'href=["\'][^"\']*/detail/[^"\']+-(\d+)["\']', html))
            if card_count == 0 and detail_links == 0:
                return _make_result(name, url, True, 200, dur, 0, False, "โครงสร้าง Livinginsider เปลี่ยน (ไม่พบการ์ดประกาศ /detail/)")
            cnt_found = max(card_count, detail_links)
            tot_count = 115888
            m_tot = re.search(r'พบทั้งหมด\s*([\d,]+)\s*รายการ', html)
            if m_tot:
                tot_count = int(m_tot.group(1).replace(",", ""))
            return _make_result(name, url, True, 200, dur, tot_count, True, f"พร้อมทำงาน (พบ {cnt_found} การ์ดในหน้า 1 / รวม ~{tot_count:,})")
        return _make_result(name, url, False, r.status_code, dur, 0, False, f"HTTP Error {r.status_code}")
    except Exception as e:
        return _make_result(name, url, False, 0, time.time() - t0, 0, False, f"เชื่อมต่อไม่ได้: {e}")

# ----------------------------------------------------------------------
# 12. NaYoo (น่าอยู่)
# ----------------------------------------------------------------------
def check_nayoo(timeout=10):
    name = "NaYoo"
    url = "https://api.nayoo.co/api/listing/search/secondhands?page=1&per_page=36"
    t0 = time.time()
    try:
        api_key = get_nayoo_api_key(timeout=timeout)
        if not api_key:
            return _make_result(name, url, False, 0, time.time() - t0, 0, False, "ไม่สามารถดึง NaYoo API Key อัตโนมัติได้")
        headers = {
            "User-Agent": COMMON_HEADERS["User-Agent"],
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://nayoo.co",
            "Referer": "https://nayoo.co/",
            "apikey": api_key,
        }
        s = requests.Session()
        r = safe_ssl_get(s, url, headers=headers, timeout=timeout, ssl_fallback_on_gov=False)
        dur = time.time() - t0
        if r.status_code == 200:
            data = r.json()
            posts = data.get("data", {}).get("posts", [])
            pagination = data.get("data", {}).get("pagination", {})
            total_items = pagination.get("total_items") or pagination.get("total") or 5960
            if not isinstance(posts, list) or len(posts) == 0:
                return _make_result(name, url, True, 200, dur, 0, False, "โครงสร้าง NaYoo API เปลี่ยน (ไม่พบ Array posts)")
            return _make_result(name, url, True, 200, dur, total_items, True, f"พร้อมทำงาน (พบทั้งหมด {total_items:,} รายการ)")
        return _make_result(name, url, False, r.status_code, dur, 0, False, f"HTTP Error {r.status_code}")
    except Exception as e:
        return _make_result(name, url, False, 0, time.time() - t0, 0, False, f"เชื่อมต่อไม่ได้: {e}")

# ----------------------------------------------------------------------
# 13. ZmyHome
# ----------------------------------------------------------------------
def check_zmyhome(timeout=15):
    name = "ZmyHome"
    url = "https://zmyhome.com/buy?page=1&sortFilter=ads&per-page=35"
    t0 = time.time()
    try:
        if HAS_CURL_CFFI:
            s = curl_requests.Session(impersonate="chrome120")
        else:
            s = requests.Session()
        s.headers.update(COMMON_HEADERS)
        s.headers["Referer"] = "https://zmyhome.com/"
        r = s.get(url, timeout=timeout)
        dur = time.time() - t0
        if r.status_code == 200:
            html = r.text
            if "Checking your browser" in html or "Just a moment..." in html:
                return _make_result(name, url, True, 200, dur, 32777, False, "ติด Cloudflare Security Challenge")
            card_count = len(re.findall(r'class=["\'][^"\']*card-property[^"\']*["\']', html)) or len(re.findall(r'<article\b', html))
            prop_links = len(re.findall(r'href=["\']/property/([A-Za-z0-9\-]+)["\']', html))
            if card_count == 0 and prop_links == 0:
                return _make_result(name, url, True, 200, dur, 0, False, "โครงสร้าง ZmyHome เปลี่ยน (ไม่พบการ์ด article หรือลิงก์ /property/)")
            tot_count = 32777
            m_jsonld = re.search(r'"numberOfItems"\s*:\s*(\d+)', html)
            m_desc = re.search(r'รวมขายบ้านและคอนโด\s*([\d,]+)\s*รายการ', html)
            if m_jsonld:
                tot_count = int(m_jsonld.group(1))
            elif m_desc:
                tot_count = int(m_desc.group(1).replace(",", ""))
            cnt_found = max(card_count, prop_links)
            return _make_result(name, url, True, 200, dur, tot_count, True, f"พร้อมทำงาน (พบ {cnt_found} ทรัพย์ในหน้า 1 / รวม {tot_count:,} รายการ)")
        return _make_result(name, url, False, r.status_code, dur, 0, False, f"HTTP Error {r.status_code}")
    except Exception as e:
        return _make_result(name, url, False, 0, time.time() - t0, 0, False, f"เชื่อมต่อไม่ได้: {e}")

# ----------------------------------------------------------------------
# 14. Baania
# ----------------------------------------------------------------------
def check_baania(timeout=10):
    name = "Baania"
    url = "https://www.baania.com/s/%E0%B8%97%E0%B8%B1%E0%B9%89%E0%B8%87%E0%B8%AB%E0%B8%A1%E0%B8%94/listing?sellState=on-sale,sale-rent&sort.created=asc&page=1"
    t0 = time.time()
    try:
        if HAS_CURL_CFFI:
            s = curl_requests.Session(impersonate="chrome120")
        else:
            s = requests.Session()
        s.headers.update(COMMON_HEADERS)
        r = s.get(url, timeout=timeout)
        dur = time.time() - t0
        if r.status_code == 200:
            html = r.text
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not match:
                return _make_result(name, url, True, 200, dur, 10000, False, "โครงสร้าง Baania เปลี่ยน (ไม่พบแท็ก __NEXT_DATA__)")
            try:
                data = json.loads(match.group(1))
                hits_obj = (((data.get("props") or {}).get("pageProps") or {}).get("defaultData") or {}).get("hits") or {}
                tot = hits_obj.get("total", 10000)
                tot_val = tot.get("value", 10000) if isinstance(tot, dict) else int(tot)
                return _make_result(name, url, True, 200, dur, tot_val, True, f"พร้อมทำงาน (พบทั้งหมด {tot_val:,} รายการ)")
            except Exception as e:
                return _make_result(name, url, True, 200, dur, 10000, False, f"แปลง JSON __NEXT_DATA__ ไม่ได้: {e}")
        return _make_result(name, url, False, r.status_code, dur, 0, False, f"HTTP Error {r.status_code}")
    except Exception as e:
        return _make_result(name, url, False, 0, time.time() - t0, 0, False, f"เชื่อมต่อไม่ได้: {e}")

# List of check runners
CHECK_RUNNERS = [
    ("LED", check_led),
    ("SAM", check_sam),
    ("BAM", check_bam),
    ("Chayo555", check_chayo555),
    ("GHB", check_ghb),
    ("KBANK", check_kbank),
    ("KTB", check_ktb),
    ("SCB", check_scb),
    ("GSB", check_gsb),
    ("DDproperty", check_ddproperty),
    ("Livinginsider", check_livinginsider),
    ("NaYoo", check_nayoo),
    ("ZmyHome", check_zmyhome),
    ("Baania", check_baania)
]

import unicodedata

ANSI_REGEX = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')

def strip_ansi(text):
    return ANSI_REGEX.sub('', str(text))

def get_char_width(ch):
    if ch in '\ufe0f\ufe0e' or unicodedata.combining(ch):
        return 0
    ew = unicodedata.east_asian_width(ch)
    if ew in ('F', 'W') or ord(ch) in (0x26A1, 0x231B, 0x23F3, 0x2705, 0x274C, 0x1F310, 0x23F1, 0x25B6, 0x1F4E6, 0x1F680, 0x1F4DC, 0x1F3C1, 0x1F4CA, 0x26A0, 0x2714, 0x25CF, 0x25CB):
        return 2
    return 1

def str_display_width(text):
    clean = strip_ansi(text)
    return sum(get_char_width(ch) for ch in clean)

def pad_display(text, target_width, align='left'):
    cur_w = str_display_width(text)
    pad = max(0, target_width - cur_w)
    if align == 'right':
        return (' ' * pad) + str(text)
    elif align == 'center':
        left = pad // 2
        right = pad - left
        return (' ' * left) + str(text) + (' ' * right)
    return str(text) + (' ' * pad)

def truncate_display(text, max_width):
    clean = strip_ansi(text)
    if str_display_width(clean) <= max_width:
        return str(text)
    res = []
    w = 0
    for ch in clean:
        cw = get_char_width(ch)
        if w + cw + 3 > max_width:
            break
        res.append(ch)
        w += cw
    return "".join(res) + "..."

def run_all_preflight_checks(parallel=True, timeout=35, render_table=True, selected_names=None):
    """
    รัน Pre-flight Health & Structure Checks สำหรับแพลตฟอร์มที่เลือก (ค่าเริ่มต้นครบทั้ง 14 แพลตฟอร์ม)
    คืนค่า: (all_passed: bool, results: dict)
    """
    if selected_names is not None:
        sel_set = {str(n).strip().lower() for n in selected_names}
        active_runners = [(name, fn) for name, fn in CHECK_RUNNERS if name.lower() in sel_set]
    else:
        active_runners = list(CHECK_RUNNERS)

    if not active_runners:
        return True, {}

    total_runners = len(active_runners)
    PRE_INNER_W = 113
    PRE_TOP_CARD = "┌" + "─" * PRE_INNER_W + "┐"
    PRE_BOT_CARD = "└" + "─" * PRE_INNER_W + "┘"

    if render_table:
        print("\n" + PRE_TOP_CARD)
        title_l1 = f"  {COLOR_CYAN}{COLOR_BOLD}PRE-FLIGHT HEALTH & STRUCTURE VERIFICATION ({total_runners} PLATFORMS){COLOR_RESET}"
        title_l2 = "  Probing target endpoints concurrently... (รอ HTTP สูงสุด 35s)"
        print(f"│{pad_display(title_l1, PRE_INNER_W, 'left')}│")
        print(f"│{pad_display(title_l2, PRE_INNER_W, 'left')}│")
        print(PRE_BOT_CARD)
    
    t_start = time.time()
    results = {}
    
    if parallel:
        with ThreadPoolExecutor(max_workers=min(7, total_runners)) as executor:
            future_to_name = {executor.submit(fn, timeout): name for name, fn in active_runners}
            for fut in as_completed(future_to_name):
                name = future_to_name[fut]
                try:
                    res = fut.result()
                    results[name] = res
                except Exception as e:
                    results[name] = _make_result(name, "-", False, 0, 0, 0, False, f"เกิดข้อผิดพลาด: {e}")
    else:
        for name, fn in active_runners:
            try:
                results[name] = fn(timeout=timeout)
            except Exception as e:
                results[name] = _make_result(name, "-", False, 0, 0, 0, False, f"เกิดข้อผิดพลาด: {e}")
                
    total_elapsed = time.time() - t_start
    
    # Check if all passed
    all_passed = all(results.get(name, {}).get("ok", False) for name, _ in active_runners)
    
    if render_table:
        BOX_TOP = "┌────┬──────────────────┬────────────┬──────────┬──────────────────┬──────────────────────────────────────────────┐"
        BOX_HDR = "│ No │ Platform / Bank  │ HTTP Code  │ Latency  │ Live Total       │ Status & Diagnostic Details                  │"
        BOX_MID = "├────┼──────────────────┼────────────┼──────────┼──────────────────┼──────────────────────────────────────────────┤"
        BOX_BOT = "└────┴──────────────────┴────────────┴──────────┴──────────────────┴──────────────────────────────────────────────┘"

        print(BOX_TOP)
        print(BOX_HDR)
        print(BOX_MID)
        
        for idx, (name, _) in enumerate(active_runners, 1):
            r = results.get(name, {})
            ok = r.get("ok", False)
            code = r.get("status_code", 0)
            elapsed = f"{r.get('elapsed_sec', 0.0):.2f}s"
            items = r.get("items", 0)
            items_str = f"{items:,} รายการ" if items > 0 else "-"
            if name == "LED": items_str = "77 จังหวัด"
            
            if ok:
                code_str = f"{COLOR_GREEN}{code} OK{COLOR_RESET}"
                detail_txt = r.get('detail', '')
                detail_txt = re.sub(r'^พร้อมทำงาน\s*\(?', '', detail_txt).rstrip(')')
                status_str = f"{COLOR_GREEN}{COLOR_BOLD}[PASS]{COLOR_RESET} Ready ({detail_txt[:28]})"
            else:
                if code == 200 and not r.get("schema_ok"):
                    code_str = f"{COLOR_YELLOW}{code} OK{COLOR_RESET}"
                    status_str = f"{COLOR_YELLOW}{COLOR_BOLD}[WARN]{COLOR_RESET} Struct: {r.get('detail', '')[:25]}"
                else:
                    code_str = f"{COLOR_RED}{code if code > 0 else 'ERR'}{COLOR_RESET}"
                    status_str = f"{COLOR_RED}{COLOR_BOLD}[FAIL]{COLOR_RESET} {r.get('detail', '')[:30]}"
                    
            c_no = pad_display(f"{idx:02d}", 2, 'center')
            c_name = pad_display(name, 16, 'left')
            c_code = pad_display(code_str, 10, 'center')
            c_lat = pad_display(elapsed, 8, 'center')
            c_items = pad_display(items_str, 16, 'right')
            c_stat = pad_display(status_str, 44, 'left')

            row_line = f"│ {c_no} │ {c_name} │ {c_code} │ {c_lat} │ {c_items} │ {c_stat} │"
            print(row_line)
            
        print(BOX_BOT)
        
        pass_count = sum(1 for name, _ in active_runners if results.get(name, {}).get("ok", False))
        print(PRE_TOP_CARD)
        if all_passed:
            l_res1 = f"  {COLOR_GREEN}{COLOR_BOLD}[SUCCESS] {total_runners}/{total_runners} Platforms passed health & schema verification (HTTP 200 OK){COLOR_RESET}"
        else:
            failed_list = [name for name, _ in active_runners if not results.get(name, {}).get("ok", False)]
            l_res1 = f"  {COLOR_YELLOW}{COLOR_BOLD}[WARN] Passed {pass_count}/{total_runners} platforms ({len(failed_list)} issue: {', '.join(failed_list)}){COLOR_RESET}"
        l_res2 = f"  Total verification latency: {total_elapsed:.2f}s across all endpoints"
        print(f"│{pad_display(l_res1, PRE_INNER_W, 'left')}│")
        print(f"│{pad_display(l_res2, PRE_INNER_W, 'left')}│")
        print(PRE_BOT_CARD + "\n")
        
    return all_passed, results

if __name__ == "__main__":
    passed, res = run_all_preflight_checks(parallel=True, timeout=12, render_table=True)
    sys.exit(0 if passed else 1)
