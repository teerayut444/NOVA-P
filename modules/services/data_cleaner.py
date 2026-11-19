import os
import sys
import re
import ast
import datetime
import threading
import urllib.parse
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st

from modules.config.constants import (
    PROPERTY_TYPE_MAPPING,
    SALE_TYPE_MAPPING,
    PROVINCE_TO_REGION,
    is_true_centroid,
    get_price_tier
)
# Candidate search paths for utility scrapers & location cleaners
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _cand in [_ROOT_DIR, os.path.join(_ROOT_DIR, "Py Scraper"), os.path.join(_ROOT_DIR, "Monthly all new"), os.path.join(_ROOT_DIR, "tools")]:
    if _cand not in sys.path and os.path.exists(_cand):
        sys.path.insert(0, _cand)

_PROJ_CACHE_LOCK = threading.Lock()

try:
    from clean_project_util import clean_project_name  # type: ignore
except Exception:
    try:
        from sam_analytics import clean_project_name  # type: ignore
    except Exception:
        def clean_project_name(name, **kwargs):
            return str(name).strip() if name else ""

try:
    from clean_location_util import translate_amphoe_en_to_th  # type: ignore
except Exception:
    def translate_amphoe_en_to_th(val):
        s = str(val or '').strip()
        return re.sub(r'[a-zA-Z\(\)\[\]]+', '', s).strip() if re.search(r'[ก-๙]', s) else 'ไม่มีข้อมูล'

_BRAND_TAG_PATTERNS = [
    (re.compile(r'eastgate|อีสท์เกต', re.I), 'Eastgate / อีสท์เกต'),
    (re.compile(r'ไอดีโอ|ไอดิโอ|ไอเดีย|ideo|idio|ไอดิโอ้|ไอดีโอ้', re.I), 'IDEO / ไอดิโอ'),
    (re.compile(r'ลุมพ[ิีึื]น[ิีึื]|lumpini|lpn', re.I), 'LPN / Lumpini'),
    (re.compile(r'พฤกษา|พฤษภา|พฤษา|พึกษา|พฤกสา|pruksa|ps\b', re.I), 'Pruksa / PS'),
    (re.compile(r'[ศส]ุ[ภพ]าลัย|supalai|spali', re.I), 'Supalai / ศุภาลัย'),
    (re.compile(r'แสนสิริ|sansiri|siri\b', re.I), 'Sansiri / แสนสิริ'),
    (re.compile(r'แอสปา[ยร์]+|aspire', re.I), 'Aspire / แอสปาย'),
    (re.compile(r'ดีคอนโด|dcondo|d\s*condo', re.I), 'Dcondo'),
    (re.compile(r'เดอะ\s*เบส|the\s*base', re.I), 'The Base'),
    (re.compile(r'ไลฟ์|life\b', re.I), 'Life'),
    (re.compile(r'ริ[ทธ]ึ่?[มม์]|rhythm', re.I), 'Rhythm'),
    (re.compile(r'ไนท์บริด[จช์]+|knightsbridge', re.I), 'Knightsbridge'),
    (re.compile(r'พลัม|plum', re.I), 'Plum'),
    (re.compile(r'คาซ่า|casa', re.I), 'Casa'),
    (re.compile(r'เซ็?นทริ[คก]|centric', re.I), 'Centric'),
    (re.compile(r'คอนโดเล็?ต|condolette', re.I), 'Condolette'),
    (re.compile(r'ยู\s*ดีไลท์|udelight', re.I), 'U Delight'),
    (re.compile(r'แชปเตอร์\s*วัน|chapter\s*one', re.I), 'Chapter One'),
    (re.compile(r'รีเจ้?นท์?|regent', re.I), 'Regent'),
    (re.compile(r'โนเบิ?ล|noble', re.I), 'Noble'),
    (re.compile(r'พาร์?คแลน[ด์]*|parkland', re.I), 'Parkland'),
    (re.compile(r'แอชตัน|ashton', re.I), 'Ashton'),
    (re.compile(r'เอล?ลิโอ|elio', re.I), 'Elio'),
    (re.compile(r'ยูนิโอ|unio', re.I), 'Unio'),
    (re.compile(r'โมดิ[ซส]|modiz', re.I), 'Modiz'),
    (re.compile(r'แอทโม[ซส]|atmoz', re.I), 'Atmoz'),
    (re.compile(r'เคฟ|kave', re.I), 'Kave'),
    (re.compile(r'แชมเบอร์?ส?|chambers', re.I), 'Chambers / แชมเบอร์ส'),
    (re.compile(r'เดอะ\s*คิวบ์?|the\s*cube', re.I), 'The Cube / เดอะคิวบ์'),
    (re.compile(r'พลีโน่?|pleno', re.I), 'Pleno / พลีโน่'),
    (re.compile(r'บริทาเนีย|britania', re.I), 'Britania'),
    (re.compile(r'ออริจิ้?น|origin', re.I), 'Origin / ออริจิ้น'),
    (re.compile(r'ริช\s*พาร์?ค|rich\s*park', re.I), 'Rich Park / ริชพาร์ค'),
    (re.compile(r'เดอะ\s*ทรี|the\s*tree', re.I), 'The Tree / เดอะทรี'),
    (re.compile(r'เมโทร\s*ลักซ์?|metro\s*luxe', re.I), 'Metro Luxe / เมโทรลักซ์'),
    (re.compile(r'เดอะ\s*ทรัสต์?|the\s*trust', re.I), 'The Trust / เดอะทรัสต์'),
    (re.compile(r'ชวนชื่?น|chuanchuen', re.I), 'Chuanchuen / ชวนชื่น'),
    (re.compile(r'เพอร์เฟ[็คกต์]+|perfect', re.I), 'Perfect / เพอร์เฟค'),
    (re.compile(r'[ภพ]ัสสร|passorn', re.I), 'Passorn / ภัสสร'),
    (re.compile(r'มั?ณฑนา|mantana', re.I), 'Mantana / มัณฑนา'),
    (re.compile(r'ชัยพฤก[ษ์ษา]+|chaiyapruek', re.I), 'Chaiyapruek / ชัยพฤกษ์'),
    (re.compile(r'วิลลาจจิ?โอ|villaggio', re.I), 'Villaggio'),
    (re.compile(r'อินดี้?|indy\b', re.I), 'Indy / อินดี้'),
    (re.compile(r'เซ็?นโทร|centro', re.I), 'Centro / เซนโทร'),
    (re.compile(r'บ้านกลางเมือง|baan\s*klang\s*muang', re.I), 'Baan Klang Muang'),
    (re.compile(r'บ้านกลางกรุง|baan\s*klang\s*krung', re.I), 'Baan Klang Krung'),
    (re.compile(r'เดอะ\s*คอนเนค|the\s*connect', re.I), 'The Connect'),
    (re.compile(r'พฤกษาวิลล์|pruksa\s*ville', re.I), 'Pruksa Ville'),
    (re.compile(r'บ้านพฤกษา|baan\s*pruksa', re.I), 'Baan Pruksa'),
    (re.compile(r'เดอะ\s*ซิตี้|the\s*city', re.I), 'The City'),
    (re.compile(r'เดอะ\s*ไลน์|the\s*line', re.I), 'The Line'),
]

def get_brand_search_tag(raw_name):
    """Returns alias search tag (e.g. IDEO / ไอดิโอ, LPN / Lumpini) to ensure instant search in Streamlit dropdown."""
    name_str = str(raw_name).strip()
    for pat, tag in _BRAND_TAG_PATTERNS:
        if pat.search(name_str):
            return tag
    return ""

_INVALID_PROJECT_SET = {
    '', '-', '--', '---', '.', '..', '...', 'nan', 'null', 'none', 'undefined',
    'ไม่ระบุ', 'ไม่มีชื่อ', 'ไม่มีข้อมูล', 'โครงการไม่มีชื่อ', 'ไม่มี',
    'โครงการ', 'หมู่บ้าน', 'คอนโด', 'บ้านเดี่ยว', 'ที่ดิน', 'ทาวน์โฮม', 'อาคารพาณิชย์', 'ห้องชุด',
    'บ้าน', 'ตึก', 'ทาวน์เฮ้าส์', 'อพาร์ทเม้นท์', 'อาคารชุด'
}
_ROOM_SCRAPE_PAT = re.compile(r'^\d+\s*ห้อง(นอน)?(\s*\d+\s*ห้องน้ำ)?', re.I)
_STUDIO_PAT = re.compile(r'^(สตูดิโอ|ห้องนอน|ห้องน้ำ|studio)$', re.I)
_AD_PITCH_PAT = re.compile(r'^(?:ขาย|ให้เช่า|เช่า|เซ้ง|ขายด่วน|ขายถูก|ด่วน|ต้องการขาย|ลดราคา|ขายบ้าน|ขายคอนโด)\b', re.I)
_COORD_PAT = re.compile(r'^-?\d{1,2}\.\d+[\s,]+-?\d{2,3}\.\d+$')
_DIGIT_ONLY_PAT = re.compile(r'^[\d.,/\s-]+$')
_GENERIC_TYPE_NUM_PAT = re.compile(r'^(บ้านเดี่ยว|บ้านแฝด|บ้าน|ทาวน์โฮม|ทาวน์เฮ้าส์|คอนโด|ห้องชุด|ที่ดิน|อาคารพาณิชย์|ตึกแถว)\s*\d+$', re.I)
_FLOOR_DESC_PAT = re.compile(r'^(?:บ้านเดี่ยว|บ้านแฝด|บ้านตึก|บ้านไม้|บ้านครึ่งตึกครึ่งไม้|บ้าน|ทาวน์เฮ้าส์|ทาวน์โฮม|ทาวเฮ้าส์|ทาวน์ฮ้าส์|ตึกแถว|อาคารพาณิชย์|อาคารโกดัง|วิลล่า|คอนโด)?\s*\d+(?:\.\d+)?\s*ชั้น\b', re.I)
_AD_NEAR_PAT = re.compile(r'^(?:ใกล้|ติด)\s*(?:bts|mrt|แอร์พอร์ต|ทางด่วน|ถนน|สถานี|ห้าง)\b', re.I)
_PRICE_IN_NAME_PAT = re.compile(r'(?:ราคา|ขายเพียง|ลดเหลือ|ผ่อนเพียง|ตรว\.ละ|วาละ|ขาย|เช่า)\s*\d+(?:\.\d+)?\s*(?:ลบ|ล้าน|แสน|บาท|บ\b)')
_ROOM_CNT_PAT = re.compile(r'(?:\d+\s*(?:ห้องนอน|ห้องน้ำ)|\d+\s*นอน\s*\d+\s*น้ำ|ห้อง(?:นอน|น้ำ)?\s*\d+\s*ห้อง)')
_AREA_SCRAPE_PAT = re.compile(r'^\d+[\d.,/-]*\s*(?:ตร\.?ว|ตร\.?ม|ตารางวา|ตารางเมตร|ไร่|วา)\b', re.I)
_AREA_MID_PAT = re.compile(r'\d+[\d.,]*\s*(?:ตร\.?ว|ตร\.?ม|ตารางวา|ตารางเมตร)\b', re.I)
_POSTAL_PREFIX_PAT = re.compile(r'^\d{5}\s*(?:บ้าน|ทาวน์|อาคาร|ที่ดิน|คอนโด|เดอะ|มบ\.|หมู่บ้าน|ทาวเฮ้าส์)', re.I)
_AD_BUZZWORDS_PAT = re.compile(r'(?:ขายด่วน|ด่วนมาก|ลดกระหน่ำ|ขายถูกที่สุด|ราคาถูกที่สุด|รีโนเวทใหม่|รีโนเวทแล้ว|ตกแต่งใหม่ทั้งหลัง|พร้อมอยู่ทันที|กู้เต็ม|กู้ได้เต็ม|ฟรีโอน|ขายขาดทุน|เจ้าของขายเอง|ผ่อนตรง|รับผ่อนตรง|agent welcomed|ขายยกแปลง)', re.I)
_CONTACT_PAT = re.compile(r'(?:โทร|tel|contact|line\s*id)\s*[:\.]?\s*\d', re.I)
_SCRAPED_DIST_PRICE_PAT = re.compile(r'ใน(?:อำเภอ|อ\.)\s*[ก-๙]+')
_AD_ADJECTIVE_PAT = re.compile(r'(?:พร้อมอยู่|ตกแต่งครบ|เฟอร์นิเจอร์|ฟรีโอน|วิวสวย|วิวทะเล|วิวสระ|ทำเลทอง)')

def is_invalid_project_name(name):
    """Detects invalid, corrupt, or scraper-polluted project names (e.g. '1 ห้อง', 'ไม่ระบุ', coordinates, pure numbers, ad headlines)."""
    if not name or pd.isna(name):
        return True
    p = str(name).strip()
    p = re.sub(r'^[\'"“‘\s]+|[\'"”’\s]+$', '', p)
    if not p or p in _INVALID_PROJECT_SET or len(p) <= 2:
        return True
    if _COORD_PAT.match(p) or _DIGIT_ONLY_PAT.match(p):
        return True
    if _GENERIC_TYPE_NUM_PAT.match(p) or _FLOOR_DESC_PAT.search(p) or _AD_NEAR_PAT.search(p):
        return True
    if _POSTAL_PREFIX_PAT.search(p) or _AREA_SCRAPE_PAT.search(p):
        return True
    if _ROOM_SCRAPE_PAT.match(p) or _STUDIO_PAT.match(p) or _AD_PITCH_PAT.search(p):
        return True
    if re.search(r'ขาย(?:คอนโด|บ้าน|ทาวน์|ที่ดิน)', p, re.I):
        return True
    if _PRICE_IN_NAME_PAT.search(p) or _ROOM_CNT_PAT.search(p) or _AD_BUZZWORDS_PAT.search(p) or _CONTACT_PAT.search(p):
        return True
    if _AREA_MID_PAT.search(p) and len(p) > 15:
        return True
    if _SCRAPED_DIST_PRICE_PAT.search(p) and 'ราคา' in p:
        return True
    if _AD_ADJECTIVE_PAT.search(p) and len(p) > 20:
        return True
    return False

def clean_display_project_name(name):
    """Normalizes formatting of project names for beautiful, clean presentation without typos/punctuation noise."""
    if not name:
        return ""
    txt = str(name).strip()
    txt = re.sub(r'^[\'"“‘\s]+|[\'"”’\s]+$', '', txt)
    if ' : ' in txt:
        parts = txt.split(' : ')
        txt = parts[1] if len(parts) > 1 else parts[0]
    
    # Standardize common brand typos and spacing in display
    txt = re.sub(r'ลุมพินี\s*ทาวน์ชิป\s*รังสิต', 'ลุมพินี ทาวน์ชิป รังสิต', txt)
    txt = re.sub(r'ทางน์ชิป|ทาวชิป|ทาวน์ซิป|ทาวนชิป', 'ทาวน์ชิป', txt)
    txt = re.sub(r'township\b', 'ทาวน์ชิป', txt, flags=re.I)
    txt = re.sub(r'\bc[\s,\.]*d[\s,\.]*e\b', 'ซีดีอี', txt, flags=re.I)
    txt = re.sub(r'\ba[\s,\.]*b\b', 'เอบี', txt, flags=re.I)
    txt = re.sub(r'\bc[\s,\.]*d\b', 'ซีดี', txt, flags=re.I)
    txt = re.sub(r'\be[\s,\.]*f\b', 'อีเอฟ', txt, flags=re.I)
    txt = re.sub(r'\bf[\s,\.]*g\b', 'เอฟจี', txt, flags=re.I)

    # Standardize popular developer names in display
    txt = re.sub(r'เดอะ\s*คิว(?:บ์|บ)', 'เดอะคิวบ์', txt)
    txt = re.sub(r'เดอะ\s*คอนเน[คกต์]+', 'เดอะ คอนเนค', txt)
    txt = re.sub(r'เดอะ\s*เบส', 'เดอะเบส', txt)
    txt = re.sub(r'เดอะ\s*ทรี', 'เดอะทรี', txt)
    txt = re.sub(r'เดอะ\s*ทรัสต์?', 'เดอะทรัสต์', txt)
    txt = re.sub(r'รีเจ้?น[ท์]*', 'รีเจ้นท์', txt)
    txt = re.sub(r'ไอดีโอ้?|ไอดิโอ้?|ไอเดีย', 'ไอดีโอ', txt)
    txt = re.sub(r'พฤกษ์?ลดา', 'พฤกษ์ลดา', txt)
    txt = re.sub(r'มั?ณฑนา', 'มัณฑนา', txt)
    txt = re.sub(r'ชัยพฤก[ษ์ษา]+', 'ชัยพฤกษ์', txt)
    txt = re.sub(r'เพอร์?เฟ[็คกต์]+', 'เพอร์เฟค', txt)
    txt = re.sub(r'วิลลาจจิ?โอ', 'วิลลาจจิโอ', txt)
    txt = re.sub(r'อินดี้?', 'อินดี้', txt)

    # Standardize comma-separated single Thai/English letters e.g. ซี,ดี,อี -> ซีดีอี, A,B,C -> ABC
    txt = re.sub(r'([ก-๙a-zA-Z])\s*,\s*([ก-๙a-zA-Z])\s*,\s*([ก-๙a-zA-Z])', r'\1\2\3', txt)
    txt = re.sub(r'([ก-๙a-zA-Z])\s*,\s*([ก-๙a-zA-Z])', r'\1\2', txt)
    # Standardize dots between single letters e.g. ซี.ดี.อี -> ซีดีอี, เอ.บี -> เอบี
    txt = re.sub(r'([ก-๙a-zA-Z])\s*\.\s*([ก-๙a-zA-Z])\s*\.\s*([ก-๙a-zA-Z])', r'\1\2\3', txt)
    txt = re.sub(r'([ก-๙a-zA-Z])\s*\.\s*([ก-๙a-zA-Z])', r'\1\2', txt)
    # Standardize spaces around hyphens and numbers
    txt = re.sub(r'\s*-\s*', '-', txt)
    txt = re.sub(r'คลอง\s*(\d+)', r'คลอง \1', txt)
    txt = re.sub(r'\s+', ' ', txt).strip()
    return txt

_PREFIX_PAT = re.compile(
    r'^(คอนโด\s*โครงการ|โครงการ\s*คอนโด|โครงการ\s*หมู่บ้าน|อาคารชุด|คอนโดมิเนียม|มีเนียม|โครงการ|หมู่บ้าน|คอนโด|บ้านเดี่ยว|บ้านแฝด|บ้าน|ทาวน์โฮม|ทาวน์เฮ้าส์|ขายคอนโด)\s*',
    re.I
)
_SUFFIX_PAT = re.compile(
    r'(\[.*?\]|\(.*?\)|\[[^\]]*$|\([^)]*$|,\s*(กรุงเทพมหานคร|กรุงเทพฯ|กรุงเทพ|นนทบุรี|ปทุมธานี|สมุทรปราการ|ชลบุรี|เชียงใหม่|ระยอง|ภูเก็ต).*$|[\s\-_/]+(?:อาคาร|ตึก)\s+[a-zA-Z0-9ก-๙]\s+ชั้น\s*\d+.*$|[\s\-_/]+ชั้น\s*\d+.*$|ชั้น\s*\d+.*$|\b(ติด|ใกล้)\s*(bts|mrt).*$)',
    re.I
)
_SPACE_CLEAN = re.compile(r'[\s\-_/.,:;()\[\]{}]+')

_NORM_PATTERNS = [
    (re.compile(r'ทางน์ชิป|ทาวชิป|ทาวน์ซิป|ทาวนชิป|\btownship\b', re.I), 'ทาวน์ชิป'),
    (re.compile(r'ซี[,\.\s]*ดี[,\.\s]*อี|\bc[\s,\.]*d[\s,\.]*e\b', re.I), 'ซีดีอี'),
    (re.compile(r'เอ[,\.\s]*บี|\ba[\s,\.]*b\b', re.I), 'เอบี'),
    (re.compile(r'ซี[,\.\s]*ดี|\bc[\s,\.]*d\b', re.I), 'ซีดี'),
    (re.compile(r'อี[,\.\s]*เอฟ|\be[\s,\.]*f\b', re.I), 'อีเอฟ'),
    (re.compile(r'เอฟ[,\.\s]*จี|\bf[\s,\.]*g\b', re.I), 'เอฟจี'),
    (re.compile(r'ซี[,\.\s]*ดี[,\.\s]*อี[,\.\s]*เอฟ|\bc[\s,\.]*d[\s,\.]*e[\s,\.]*f\b', re.I), 'ซีดีอีเอฟ'),
    (re.compile(r'บี[.\s]*เค[.\s]*|\bb[\s\.]*k\b', re.I), 'บีเค'),
    (re.compile(r'เอส[.\s]*ซี[.\s]*|\bs[\s\.]*c\b', re.I), 'เอสซี'),
    (re.compile(r'\bklong\b', re.I), 'คลอง'),
    (re.compile(r'\brangsit\b', re.I), 'รังสิต'),
    (re.compile(r'\bsukhumvit\b', re.I), 'สุขุมวิท'),
    (re.compile(r'\brama\b', re.I), 'พระราม'),
    (re.compile(r'\b(?:sathorn|sathon)\b', re.I), 'สาทร'),
    (re.compile(r'\b(?:asoke|asok)\b', re.I), 'อโศก'),
    (re.compile(r'\b(?:ladprao|latphrao)\b', re.I), 'ลาดพร้าว'),
    (re.compile(r'\btiwanon\b', re.I), 'ติวานนท์'),
    (re.compile(r'\b(?:bangna|bang\s*na)\b', re.I), 'บางนา'),
    (re.compile(r'\bratchada\b', re.I), 'รัชดา'),
    (re.compile(r'\b(?:thonglor|thong\s*lo)\b', re.I), 'ทองหล่อ'),
    (re.compile(r'\b(?:ekkamai|ekamai)\b', re.I), 'เอกมัย'),
    (re.compile(r'\bsilom\b', re.I), 'สีลม'),
    (re.compile(r'\bmobi\b', re.I), 'โมบิ'),
    (re.compile(r'\bville\b', re.I), 'วิลล์'),
    (re.compile(r'\bpark\b|ปาร์ค', re.I), 'พาร์ค'),
    (re.compile(r'\bplace\b', re.I), 'เพลส'),
    (re.compile(r'\bprime\b', re.I), 'ไพร์ม'),
    (re.compile(r'\bveranda\b', re.I), 'เวอเรนด้า'),
    (re.compile(r'\bcampus\b', re.I), 'แคมปัส'),
    (re.compile(r'\bresort\b', re.I), 'รีสอร์ท'),
    (re.compile(r'\bstation\b', re.I), 'สเตชั่น'),
    (re.compile(r'\bcondo\b', re.I), 'คอนโด'),
    (re.compile(r'ไอดีโอ้?|ไอดิโอ้?|ไอเดีย|\b(?:ideo|idio)\b', re.I), 'ไอดีโอ'),
    (re.compile(r'ลุมพ[ิีึื]น[ิีึื]|\b(?:lumpini|lpn)\b', re.I), 'ลุมพินี'),
    (re.compile(r'พฤกษา|พฤษภา|พฤษา|พึกษา|พฤกสา|พฤษษา|พฤกษภ|\b(?:pruksa|ps)\b', re.I), 'พฤกษา'),
    (re.compile(r'[ศส]ุ[ภพ]าลัย|\b(?:supalai|spali)\b', re.I), 'ศุภาลัย'),
    (re.compile(r'แสนสิริ|\b(?:sansiri|siri)\b', re.I), 'แสนสิริ'),
    (re.compile(r'แอสปา[ยร์]+|\baspire\b', re.I), 'แอสปาย'),
    (re.compile(r'ดีคอนโด|\b(?:dcondo|d\s*condo)\b', re.I), 'ดีคอนโด'),
    (re.compile(r'เดอะ\s*เบส|\bthe\s*base\b', re.I), 'เดอะเบส'),
    (re.compile(r'ไลฟ์|\blife\b', re.I), 'ไลฟ์'),
    (re.compile(r'ริ[ทธ]ึ่?[มม์]|\brhythm\b', re.I), 'ริทึ่ม'),
    (re.compile(r'ไนท์บริด[จช์]*|\bknightsbridge\b', re.I), 'ไนท์บริดจ์'),
    (re.compile(r'พลัม|\bplum\b', re.I), 'พลัม'),
    (re.compile(r'คาซ[่า]|\bcasa\b', re.I), 'คาซ่า'),
    (re.compile(r'เซ็?นทริ[คก]|\bcentric\b', re.I), 'เซ็นทริค'),
    (re.compile(r'คอนโดเล็?ต|\bcondolette\b', re.I), 'คอนโดเลต'),
    (re.compile(r'ยู\s*ดีไลท์|\bu\s*delight\b', re.I), 'ยูดีไลท์'),
    (re.compile(r'แชปเตอร์\s*วัน|\bchapter\s*one\b', re.I), 'แชปเตอร์วัน'),
    (re.compile(r'รีเจ้?น[ท์]*|\bregent\b', re.I), 'รีเจ้นท์'),
    (re.compile(r'โนเบิ?ล|\bnoble\b', re.I), 'โนเบิล'),
    (re.compile(r'พาร์?คแลน[ด์]*|\bparkland\b', re.I), 'พาร์คแลนด์'),
    (re.compile(r'แอชตัน|\bashton\b', re.I), 'แอชตัน'),
    (re.compile(r'เอล?ลิโอ|\belio\b', re.I), 'เอลิโอ'),
    (re.compile(r'ยูนิโอ|\bunio\b', re.I), 'ยูนิโอ'),
    (re.compile(r'โมดิ[ซสช]|\bmodiz\b', re.I), 'โมดิซ'),
    (re.compile(r'แอทโม[ซส]|\batmoz\b', re.I), 'แอทโมซ'),
    (re.compile(r'เคฟ|\bkave\b', re.I), 'เคฟ'),
    (re.compile(r'แชมเบอร์?ส?|\bchambers\b', re.I), 'แชมเบอร์ส'),
    (re.compile(r'เดอะ\s*คิว(?:บ์|บ)?|\bthe\s*cube\b', re.I), 'เดอะคิวบ์'),
    (re.compile(r'พลีโน่?|\bpleno\b', re.I), 'พลีโน่'),
    (re.compile(r'บริทาเนีย|\bbritani?a\b', re.I), 'บริทาเนีย'),
    (re.compile(r'ออริจิ้?น|\borigin\b', re.I), 'ออริจิ้น'),
    (re.compile(r'ริช\s*พาร์?ค|\brich\s*park\b', re.I), 'ริชพาร์ค'),
    (re.compile(r'เดอะ\s*ทรี|\bthe\s*tree\b', re.I), 'เดอะทรี'),
    (re.compile(r'เมโทร\s*ลักซ์?|\bmetro\s*luxe\b', re.I), 'เมโทรลักซ์'),
    (re.compile(r'เดอะ\s*ทรัสต์?|\bthe\s*trust\b', re.I), 'เดอะทรัสต์'),
    (re.compile(r'ชวนชื่?น|\b(?:chuanchuen|chuan\s*chuen)\b', re.I), 'ชวนชื่น'),
    (re.compile(r'เพอร์?เฟ[็คกต์]+|\bperfect\b', re.I), 'เพอร์เฟค'),
    (re.compile(r'[ภพ]ัสสร|\bpassorn\b', re.I), 'ภัสสร'),
    (re.compile(r'มั?ณฑนา|\bmantana\b', re.I), 'มัณฑนา'),
    (re.compile(r'ชัยพฤก[ษ์ษา]+|\bchaiyapruek\b', re.I), 'ชัยพฤกษ์'),
    (re.compile(r'วิลลาจจิ?โอ|\bvillaggio\b', re.I), 'วิลลาจจิโอ'),
    (re.compile(r'อินดี้?|\bindy\b', re.I), 'อินดี้'),
    (re.compile(r'ฮาบิเทีย|\bhabitia\b', re.I), 'ฮาบิเทีย'),
    (re.compile(r'ส[ะา]ราญสิริ|\bsaransiri\b', re.I), 'สราญสิริ'),
    (re.compile(r'บุราสิริ|\bburasiri\b', re.I), 'บุราสิริ'),
    (re.compile(r'[เศส]รษฐสิริ|\bsetthasiri\b', re.I), 'เศรษฐสิริ'),
    (re.compile(r'นาราสิริ|\bnarasiri\b', re.I), 'นาราสิริ'),
    (re.compile(r'คณาสิริ|\bkanasiri\b', re.I), 'คณาสิริ'),
    (re.compile(r'อณาสิริ|\banasiri\b', re.I), 'อณาสิริ'),
    (re.compile(r'เซ็?นโทร|\bcentro\b', re.I), 'เซนโทร'),
    (re.compile(r'บ้านกลางเมือง|\bbaan\s*klang\s*muang\b', re.I), 'บ้านกลางเมือง'),
    (re.compile(r'บ้านกลางกรุง|\bbaan\s*klang\s*krung\b', re.I), 'บ้านกลางกรุง'),
    (re.compile(r'ซิตี้เซนส์?|\bcity\s*sense\b', re.I), 'ซิตี้เซนส์'),
    (re.compile(r'เดอะ\s*คอนเน[คกต์]+|\bthe\s*connect\b', re.I), 'เดอะ คอนเนค'),
    (re.compile(r'พฤกษาวิลล์?|\bpruksa\s*ville\b', re.I), 'พฤกษาวิลล์'),
    (re.compile(r'บ้านพฤกษา|\bbaan\s*pruksa\b', re.I), 'บ้านพฤกษา'),
    (re.compile(r'เดอะ\s*ซิตี้|\bthe\s*city\b', re.I), 'เดอะ ซิตี้'),
    (re.compile(r'เดอะ\s*ไลน์|\bthe\s*line\b', re.I), 'เดอะ ไลน์'),
    (re.compile(r'สินมั่?นคง', re.I), 'สินมั่นคง'),
    (re.compile(r'ทิพมา[ศส]', re.I), 'ทิพมาศ'),
    (re.compile(r'คาร์พ[ิี]เดี้ย?ม', re.I), 'คาร์พิเดียม'),
    (re.compile(r'เดอะ\s*คันทรี?่?|\bthe\s*country\b', re.I), 'เดอะคันทรี'),
    (re.compile(r'โมเดิร?์?น|\bmodern\b', re.I), 'โมเดิร์น'),
    (re.compile(r'โฮม|\bhome\b', re.I), 'โฮม'),
    (re.compile(r'เบญจทรัพย์', re.I), 'เบญจทรัพย์'),
    (re.compile(r'แพรมาพร', re.I), 'แพรมาพร'),
    (re.compile(r'ทรัพย์รุ่งเรือง', re.I), 'ทรัพย์รุ่งเรือง'),
    (re.compile(r'แบงค์?\s*คอก\s*ฮอไรซอน|\bbangkok\s*horizon\b', re.I), 'แบงค์คอก ฮอไรซอน'),
    (re.compile(r'พฤกษ์?ลดา|\bprueklada\b', re.I), 'พฤกษ์ลดา'),
    (re.compile(r'กัสโต้|\bgusto\b', re.I), 'กัสโต้'),
    (re.compile(r'ควอลิตี้\s*เฮ้าส์|\b(?:quality\s*house|q\.?\s*house)\b', re.I), 'ควอลิตี้ เฮ้าส์'),
    (re.compile(r'แลนด์\s*แอนด์?\s*เฮ้าส์?|\bland\s*(?:&|and)\s*house\b', re.I), 'แลนด์ แอนด์ เฮ้าส์'),
    (re.compile(r'อีสท์เกต|\beastgate\b', re.I), 'อีสท์เกต'),
]

def normalize_project_name(s):
    """Normalizes project names to link variations (e.g. ไอดิโอ <-> ไอดีโอ <-> IDEO)."""
    if not s or pd.isna(s):
        return ''
    txt = str(s).strip()
    txt = re.sub(r'^[\'"“‘\s]+|[\'"”’\s]+$', '', txt)
    if ' : ' in txt:
        parts = txt.split(' : ')
        txt = parts[1] if len(parts) > 1 else parts[0]
    while True:
        nt = _PREFIX_PAT.sub('', txt).strip()
        if nt == txt:
            break
        txt = nt
    txt = _SUFFIX_PAT.sub('', txt).strip()

    # Normalize numbers with common Thai real-estate prefixes
    txt = re.sub(r'คลอง\s*(\d+)', r'คลอง\1', txt)
    txt = re.sub(r'เฟส\s*(\d+)', r'เฟส\1', txt)
    txt = re.sub(r'ซอย\s*(\d+)', r'ซอย\1', txt)
    txt = re.sub(r'สาย\s*(\d+)', r'สาย\1', txt)
    txt = re.sub(r'phase\s*(\d+)', r'เฟส\1', txt, flags=re.I)

    for pat, rep in _NORM_PATTERNS:
        txt = pat.sub(rep, txt)

    res = _SPACE_CLEAN.sub('', txt)
    res = res.lower()
    res = re.sub(r'[่้๊๋์็]', '', res)
    res = res.replace('ศ', 'ส').replace('ษ', 'ส').replace('ภ', 'พ').replace('ธ', 'ท')
    res = res.replace('ณ', 'น').replace('ญ', 'ย').replace('ฌ', 'ช').replace('ฬ', 'ล')
    res = res.replace('ี', 'ิ').replace('ื', 'ิ').replace('ึ', 'ิ')
    if res in ['บ้าน', 'คอนโด', 'ที่ดิน', 'ทาวน์โฮม', 'อาคารพาณิชย์', '']:
        return ''
    return res

def _strip_excel_text_formula(s):
    """Strips Excel CSV text formula wrapper like =\"1-1-1\" or leading apostrophe '1-1-1."""
    s = str(s).strip()
    if s.startswith('="') and s.endswith('"') and len(s) >= 3:
        return s[2:-1].strip()
    if s.startswith("'"):
        return s[1:].strip()
    return s

def parse_area_to_sqwah(area_str):
    """Helper function to parse 'พื้นที่ (ไร่-งาน-วา)' to square wah."""
    if pd.isna(area_str) or not isinstance(area_str, str) or str(area_str).strip() == "":
        return np.nan
    area_str = _strip_excel_text_formula(area_str)
    
    parts = area_str.split('-')
    if len(parts) == 3:
        try:
            rai = float(parts[0]) if parts[0] else 0.0
            ngan = float(parts[1]) if parts[1] else 0.0
            wah = float(parts[2]) if parts[2] else 0.0
            return (rai * 400.0) + (ngan * 100.0) + wah
        except ValueError:
            pass
    elif len(parts) == 1:
        try:
            return float(parts[0].replace(',', '').strip())
        except ValueError:
            pass
            
    try:
        rai_match = re.search(r'([\d,]+(?:\.\d+)?)\s*ไร่', area_str)
        rai = float(rai_match.group(1).replace(',', '')) if rai_match else 0.0
        
        ngan_match = re.search(r'([\d,]+(?:\.\d+)?)\s*งาน', area_str)
        ngan = float(ngan_match.group(1).replace(',', '')) if ngan_match else 0.0
        
        wah_match = re.search(r'([\d,]+(?:\.\d+)?)\s*(?:ตารางวา|ตร\.ว\.|วา)', area_str)
        wah = float(wah_match.group(1).replace(',', '')) if wah_match else 0.0
        
        if rai > 0 or ngan > 0 or wah > 0:
            return (rai * 400.0) + (ngan * 100.0) + wah
    except Exception:
        pass
        
    return np.nan

def to_float_sqwah(val):
    """Converts any value (numeric or string like '2-0-57', '1 ไร่ 2 งาน', '50.5') to float square wah."""
    if pd.isna(val):
        return np.nan
    if isinstance(val, (int, float, np.number)):
        return float(val) if float(val) > 0 else np.nan
    val_str = _strip_excel_text_formula(val).replace(',', '')
    if not val_str or val_str in ['nan', 'None', '-', '']:
        return np.nan
    try:
        f = float(val_str)
        return f if f > 0 else np.nan
    except (ValueError, TypeError):
        return parse_area_to_sqwah(_strip_excel_text_formula(val))

def to_float_sqm(val):
    """Converts any usable area value to float square meters."""
    if pd.isna(val):
        return np.nan
    if isinstance(val, (int, float, np.number)):
        return float(val) if float(val) > 0 else np.nan
    val_str = str(val).strip()
    if not val_str or val_str in ['nan', 'None', '-', '']:
        return np.nan
    try:
        m = re.search(r'([\d,]+(?:\.\d+)?)', val_str)
        if not m:
            return np.nan
        f = float(m.group(1).replace(',', ''))
        return f if f > 0 else np.nan
    except (ValueError, TypeError):
        return np.nan

def format_to_rai_ngan_wah(val):
    """Formats any land area value (sqwah float or text like '0-0-67' or '1 ไร่ 2 งาน') to 'X-Y-Z' (ไร่-งาน-ตร.ว.)"""
    if pd.isna(val):
        return "-"
    val_str = _strip_excel_text_formula(val)
    if not val_str or val_str in ['nan', 'None', '-', '0', '0-0-0', '0-0-0.0']:
        return "-"
    if re.match(r'^\d+-\d+-\d+(?:\.\d+)?$', val_str):
        return "-" if val_str in ['0-0-0', '0-0-0.0'] else val_str
    sqwah = to_float_sqwah(val)
    if pd.isna(sqwah) or sqwah <= 0:
        return "-"
    sqwah = round(sqwah, 4)
    rai = int(sqwah // 400)
    rem = round(sqwah % 400, 4)
    ngan = int(rem // 100)
    wah = round(rem % 100, 2)
    if wah >= 100.0:
        ngan += int(wah // 100)
        wah = round(wah % 100, 2)
    if ngan >= 4:
        rai += ngan // 4
        ngan = ngan % 4
    wah_str = str(int(wah)) if wah == int(wah) else f"{wah:.1f}"
    return f"{rai}-{ngan}-{wah_str}"

def _parse_announcement_date(s):
    """Parse Thai/CE date strings (full date preferred over year-only); returns (datetime.date | None, year_only_diff | None)."""
    # 1. Full d/m/yyyy (with optional HH:MM[:SS]) - handles BE years >= 2400
    m_dmy = re.match(r'^(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?$', s)
    if m_dmy:
        d_i, m_i, y_i = int(m_dmy.group(1)), int(m_dmy.group(2)), int(m_dmy.group(3))
        if y_i >= 2400:
            y_i -= 543
        try:
            return datetime.date(y_i, m_i, d_i), None
        except ValueError:
            pass

    # 2. ISO yyyy-mm-dd / timestamp
    m_iso = re.match(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})', s)
    if m_iso:
        y_i, m_i, d_i = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        if y_i >= 2400:
            y_i -= 543
        try:
            return datetime.date(y_i, m_i, d_i), None
        except ValueError:
            pass

    # 3. General pandas fallback (explicit dayfirst for non-ISO non-year strings)
    if not re.match(r'^(?:ปี\s*)?\d{4}(?:\.0+)?$', s):
        is_iso_like = bool(re.match(r'^\d{4}[-/]', s))
        dt = pd.to_datetime(s, errors='coerce', dayfirst=not is_iso_like, utc=True)
        if not pd.isna(dt):
            d = dt.date()
            if d.year >= 2400:
                try:
                    d = datetime.date(d.year - 543, d.month, d.day)
                except ValueError:
                    pass
            return d, None

    # 4. Year-only formats: 'ปี 2556', '2569', '2024.0'
    m_be = re.search(r'(?:ปี\s*)?(\b25\d{2}\b)', s)
    if m_be:
        return None, int(m_be.group(1)) - 543

    m_yr = re.match(r'^(\b19\d{2}|\b20\d{2})(?:\.0+)?$', s)
    if m_yr:
        return None, int(m_yr.group(1))

    return None, None

def format_announcement_age(val, ref_date=None):
    """
    Calculates the elapsed duration from an announcement date until today in 'X ปี Y เดือน' format:
    - >= 1 year with months: '1 ปี 3 เดือน'
    - >= 1 year with 0 months: '2 ปี'
    - < 1 year: '5 เดือน'
    - < 1 month: '< 1 เดือน'
    - Year-only input (e.g. '2024.0', 'ปี 2556'): '2 ปี', '13 ปี'
    - Empty, missing, or invalid: '-'
    """
    if ref_date is None:
        ref_date = datetime.date.today()
    if pd.isna(val) or val is None:
        return "-"
    s = str(val).strip()
    if not s or s in ['-', 'nan', 'None', '<NA>', 'null', '0', '0.0', 'ไม่มีข้อมูล']:
        return "-"

    try:
        d, yr_only = _parse_announcement_date(s)
        if yr_only is not None:
            diff_yr = ref_date.year - yr_only
            if diff_yr > 0:
                return f"{diff_yr} ปี"
            elif diff_yr == 0:
                return "< 1 ปี"
            return "-"
        if d is None:
            return "-"
        if d > ref_date:
            return "< 1 เดือน"

        total_months = (ref_date.year - d.year) * 12 + (ref_date.month - d.month)
        if ref_date.day < d.day:
            total_months -= 1
        if total_months < 0:
            total_months = 0

        years = total_months // 12
        months = total_months % 12

        if years > 0 and months > 0:
            return f"{years} ปี {months} เดือน"
        elif years > 0 and months == 0:
            return f"{years} ปี"
        elif years == 0 and months > 0:
            return f"{months} เดือน"
        else:
            return "< 1 เดือน"
    except Exception:
        return "-"

def parse_listing_age_days(val, ref_date=None):
    """
    Parses announcement date and returns elapsed age in days (integer >= 0).
    Returns -1 if missing, empty, or unparseable.
    """
    if ref_date is None:
        ref_date = datetime.date.today()
    if pd.isna(val) or val is None:
        return -1
    s = str(val).strip()
    if not s or s in ['-', 'nan', 'None', '<NA>', 'null', '0', '0.0', 'ไม่มีข้อมูล']:
        return -1

    try:
        d, yr_only = _parse_announcement_date(s)
        if d is not None:
            return max(0, (ref_date - d).days)
        if yr_only is not None:
            return max(0, (ref_date.year - yr_only) * 365)
    except Exception:
        pass

    return -1

def parse_floor_numeric(val):
    """
    Extracts numeric floor number or building floor count from string/number.
    Returns float >= 0, or -1.0 if missing/unspecified.
    """
    if pd.isna(val) or val is None:
        return -1.0
    s = str(val).strip()
    if s in ['', '-', 'nan', 'None', '<NA>', 'null', 'ไม่ระบุ', 'ไม่มีข้อมูล']:
        return -1.0
    m = re.search(r'(\d+(?:\.\d+)?)', s)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            return -1.0
    return -1.0

def parse_room_count(val):
    """
    Extracts room/parking count.
    Returns float >= 0 (0.0 for studio/none), or -1.0 if missing/unspecified.
    """
    if pd.isna(val) or val is None:
        return -1.0
    s = str(val).strip().lower()
    if s in ['', '-', 'nan', 'none', '<na>', 'null', 'ไม่ระบุ', 'ไม่มีข้อมูล']:
        return -1.0
    if 'สตูดิโอ' in s or 'studio' in s:
        return 0.0
    try:
        f = float(s)
        return f if f >= 0 else -1.0
    except (ValueError, TypeError):
        m = re.search(r'(\d+(?:\.\d+)?)', s)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, TypeError):
                return -1.0
        return -1.0

def format_num_val(val):
    """Safely format numeric fields (e.g., bedrooms, area) to nice string."""
    if pd.isna(val) or str(val).strip() == "" or str(val).lower() == "nan" or val is None or str(val).lower() == "$undefined":
        return ""
    try:
        f_val = float(val)
        if f_val.is_integer():
            return str(int(f_val))
        return str(f_val)
    except ValueError:
        return str(val)

def get_clean_title(val):
    """Clean property title string."""
    if not val or pd.isna(val):
        return "ไม่มีชื่อประกาศ"
    val_str = str(val).strip()
    if val_str.startswith("{") and val_str.endswith("}"):
        try:
            d = ast.literal_eval(val_str)
            if isinstance(d, dict):
                return d.get('th') or d.get('en') or val_str
        except Exception:
            pass
    return val_str

def get_clean_link(val):
    """Clean property link string."""
    if not val or pd.isna(val):
        return ""
    val_str = str(val).strip()
    if val_str.startswith("{") and val_str.endswith("}"):
        try:
            d = ast.literal_eval(val_str)
            if isinstance(d, dict):
                return d.get('th') or d.get('en') or val_str
        except Exception:
            pass
    return val_str

def format_coord_vectorized(df, coord_col):
    """Vectorized coordinate formatting with centroid warning prefix ('⚠️ ') and '-' fallback."""
    if df is None or df.empty or coord_col not in df.columns:
        return pd.Series('-', index=df.index if df is not None else [])
    vals = pd.to_numeric(df[coord_col], errors='coerce')
    valid_mask = vals.notna() & (vals != 0)
    if not valid_mask.any():
        return pd.Series('-', index=df.index)
    if 'is_centroid' in df.columns:
        c_raw = df['is_centroid']
        if pd.api.types.is_bool_dtype(c_raw.dtype):
            is_cen = c_raw.fillna(False).astype(bool)
        else:
            is_cen = c_raw.fillna('').astype(str).str.strip().str.lower().isin({'true', '1', '1.0', 'yes', 't'})
    else:
        is_cen = pd.Series(False, index=df.index)
    formatted = pd.Series('-', index=df.index, dtype=object)
    valid_vals = vals[valid_mask]
    valid_cen = is_cen[valid_mask]
    formatted.loc[valid_mask] = [
        f"⚠️ {v:.6f}" if c else f"{v:.6f}"
        for v, c in zip(valid_vals, valid_cen)
    ]
    return formatted

@st.cache_data(show_spinner=False)
def _get_dataset_month_year_cached(_df, cache_key, exclude_legal=True):
    """Formats dataset date into Thai Month & Year (e.g. สิงหาคม 2569) and date range from start to latest extraction date."""
    thai_full_months = [
        'มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน',
        'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม'
    ]
    thai_short_months = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']
    
    if _df is not None and not _df.empty and 'วันที่ดึงข้อมูล' in _df.columns:
        target_df = _df
        # Sidebar ที่บอกดึงข้อมูล ไม่ต้องนับของ LED Legal / LED_SOLD
        if exclude_legal and 'บริษัท' in _df.columns:
            legal_mask = _df['บริษัท'].astype(str).str.strip().str.upper().isin(['LED LEGAL', 'LED_LEGAL', 'LED_SOLD', 'LED SOLD'])
            non_legal = _df[~legal_mask]
            if not non_legal.empty:
                target_df = non_legal

        s_date = target_df['วันที่ดึงข้อมูล'].dropna().astype(str).str.strip()
        s_date = s_date[~s_date.isin(['', 'nan', 'None', '-'])]
        if not s_date.empty:
            try:
                is_iso = s_date.str.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}')
                dts = pd.Series(index=s_date.index, dtype='datetime64[ns]')
                if is_iso.any():
                    dts.loc[is_iso] = pd.to_datetime(s_date[is_iso], format='mixed', dayfirst=False, errors='coerce')
                if (~is_iso).any():
                    dts.loc[~is_iso] = pd.to_datetime(s_date[~is_iso], format='mixed', dayfirst=True, errors='coerce')
                dts = dts.dropna()
                
                if not dts.empty:
                    min_dt = dts.min()
                    min_year = min_dt.year + 543 if min_dt.year < 2500 else min_dt.year
                    
                    month_name = thai_full_months[min_dt.month - 1]
                    min_short_m = thai_short_months[min_dt.month - 1]
                    
                    month_year_str = f"{month_name} {min_year}"
                    exact_date_str = f"{min_dt.day} {min_short_m} {min_year}"
                        
                    return month_year_str, exact_date_str
            except Exception:
                pass
    try:
        p_path = next((p for p in [
            Path("all_assets.parquet"),
            Path("all_asset.parquet"),
            Path(_ROOT_DIR) / "all_assets.parquet",
            Path(_ROOT_DIR) / "all_asset.parquet",
        ] if p.exists()), None)
        if p_path is not None:
            dt = datetime.datetime.fromtimestamp(p_path.stat().st_mtime)
            thai_year = dt.year + 543 if dt.year < 2500 else dt.year
            month_name = thai_full_months[dt.month - 1]
            short_month = thai_short_months[dt.month - 1]
            return f"{month_name} {thai_year}", f"{dt.day} {short_month} {thai_year}"
    except Exception:
        pass
    now_dt = datetime.datetime.now()
    fallback_year = now_dt.year + 543 if now_dt.year < 2500 else now_dt.year
    return f"{thai_full_months[now_dt.month - 1]} {fallback_year}", f"{now_dt.day} {thai_short_months[now_dt.month - 1]} {fallback_year}"

def get_dataset_month_year(_df, data_mtime=None, exclude_legal=True):
    """Formats dataset date into Thai Month & Year with automatic cache invalidation when dataset updates."""
    if data_mtime is None:
        try:
            p_path = next((p for p in [
                Path("all_assets.parquet"),
                Path("all_asset.parquet"),
                Path(_ROOT_DIR) / "all_assets.parquet",
                Path(_ROOT_DIR) / "all_asset.parquet",
            ] if p.exists()), None)
            data_mtime = p_path.stat().st_mtime if p_path is not None else 0.0
        except Exception:
            data_mtime = 0.0
    row_cnt = len(_df) if _df is not None else 0
    return _get_dataset_month_year_cached(_df, cache_key=(data_mtime, row_cnt, exclude_legal, 'no_led_legal_v1'), exclude_legal=exclude_legal)

def _apply_led_legal_sold_prices(df):
    """For LED Legal (LED_SOLD): uses 'ราคาขายได้' as the selling price 'ราคา'
    and recalculates per-sqw and per-sqm unit rates based on the actual sold price.
    """
    if 'บริษัท' in df.columns and 'ราคาขายได้' in df.columns and 'ราคา' in df.columns:
        legal_sold_mask = df['บริษัท'].astype(str).str.strip().str.upper().isin(['LED LEGAL', 'LED_LEGAL', 'LED_SOLD'])
        if legal_sold_mask.any():
            if df['ราคา'].dtype != 'float64':
                df['ราคา'] = df['ราคา'].astype('float64')
            sold_p = pd.to_numeric(df.loc[legal_sold_mask, 'ราคาขายได้'], errors='coerce')
            valid_sold = sold_p.notna() & (sold_p >= 500)
            if valid_sold.any():
                target_idx = sold_p[valid_sold].index
                df.loc[target_idx, 'ราคา'] = sold_p.loc[target_idx]

                sqw_col = 'พื้นที่_ตารางวา' if 'พื้นที่_ตารางวา' in df.columns else ('เนื้อที่ (ตร.ว.)' if 'เนื้อที่ (ตร.ว.)' in df.columns else None)
                if sqw_col and 'ราคาต่อตารางวา' in df.columns:
                    if df['ราคาต่อตารางวา'].dtype != 'float64':
                        df['ราคาต่อตารางวา'] = pd.to_numeric(df['ราคาต่อตารางวา'], errors='coerce').astype('float64')
                    sqw_vals = pd.to_numeric(df.loc[target_idx, sqw_col], errors='coerce')
                    new_puw = np.where((sqw_vals > 0) & (sold_p.loc[target_idx] > 0), sold_p.loc[target_idx] / sqw_vals, np.nan)
                    df.loc[target_idx, 'ราคาต่อตารางวา'] = pd.Series(new_puw, index=target_idx, dtype='float64')

                if 'พื้นที่ใช้สอย (ตร.ม.)' in df.columns and 'ราคาต่อตารางเมตร' in df.columns:
                    if df['ราคาต่อตารางเมตร'].dtype != 'float64':
                        df['ราคาต่อตารางเมตร'] = pd.to_numeric(df['ราคาต่อตารางเมตร'], errors='coerce').astype('float64')
                    sqm_vals = pd.to_numeric(df.loc[target_idx, 'พื้นที่ใช้สอย (ตร.ม.)'], errors='coerce')
                    new_pum = np.where((sqm_vals > 0) & (sold_p.loc[target_idx] > 0), sold_p.loc[target_idx] / sqm_vals, np.nan)
                    df.loc[target_idx, 'ราคาต่อตารางเมตร'] = pd.Series(new_pum, index=target_idx, dtype='float64')
    return df


def ensure_derived_cols(df):
    """Enriches and normalizes the properties dataset with standard columns, categories, and parsed values."""
    if df is None or df.empty:
        return df

    # Fast-path: if ALL rows are already pre-cleaned and derived, skip heavy regex pipeline!
    if '_is_derived_clean' in df.columns:
        is_all_clean = bool(df['_is_derived_clean'].fillna(False).astype(bool).all()) if len(df) > 0 else False
        if is_all_clean:
            if 'is_centroid' in df.columns:
                df['is_centroid'] = df['is_centroid'].apply(is_true_centroid).astype(bool) if not pd.api.types.is_bool_dtype(df['is_centroid'].dtype) else df['is_centroid'].fillna(False).astype(bool)
            if 'โจทก์' in df.columns:
                df['โจทก์'] = df['โจทก์'].fillna('').astype(str).replace({'nan': '', 'None': '', 'null': '', '<NA>': '', 'NaN': '', '-': ''}).str.strip()
                try:
                    from clean_location_util import clean_plaintiff_name
                    df['โจทก์'] = df['โจทก์'].apply(clean_plaintiff_name)
                except ImportError:
                    pass
            for f64_col in ['ราคา', 'ราคาขายได้', 'ละติจูด', 'ลองจิจูด', 'พื้นที่_ตารางวา', 'พื้นที่ใช้สอย (ตร.ม.)', 'ราคาต่อตารางวา', 'ราคาต่อตารางเมตร']:
                if f64_col in df.columns and df[f64_col].dtype != 'float64':
                    df[f64_col] = pd.to_numeric(df[f64_col], errors='coerce').astype('float64')
            if 'norm_project_name' not in df.columns:
                if 'ชื่อโครงการ' in df.columns:
                    u_projs = df['ชื่อโครงการ'].dropna().unique()
                    norm_map = {p: normalize_project_name(p) for p in u_projs if p}
                    df['norm_project_name'] = df['ชื่อโครงการ'].map(norm_map).fillna('')
                else:
                    df['norm_project_name'] = ''
            if 'ลิงก์' in df.columns:
                link_s = df['ลิงก์'].astype(str)
                rel_bridge_mask = link_s.str.startswith('app/static/led_')
                if rel_bridge_mask.any():
                    df.loc[rel_bridge_mask, 'ลิงก์'] = '/' + link_s.loc[rel_bridge_mask]
            for col in ['บริษัท', 'ประเภททรัพย์', 'จังหวัด', 'ภาค', 'ประเภทการขาย']:
                if col in df.columns and not isinstance(df[col].dtype, pd.CategoricalDtype):
                    df[col] = df[col].astype('category')
            df = _apply_led_legal_sold_prices(df)
            return df

    if 'ประเภททรัพย์' in df.columns:
        prop_type_map = PROPERTY_TYPE_MAPPING
        u_types = df['ประเภททรัพย์'].dropna().unique()
        lower_prop_map = {k.lower(): v for k, v in prop_type_map.items()}

        def _resolve_single_type(t):
            s = str(t).strip()
            if s in prop_type_map:
                return prop_type_map[s]
            sl = s.lower()
            if sl in lower_prop_map:
                return lower_prop_map[sl]
            if sl.startswith('semi-detached') or 'twin house' in sl:
                return 'บ้านแฝด'
            if 'ทาวน์' in sl or sl.startswith('town'):
                return 'ทาวน์เฮ้าส์'
            if 'condo' in sl or sl in ['penthouse', 'duplex']:
                return 'ห้องชุดพักอาศัย'
            if sl.startswith('villa'):
                return 'วิลล่า'
            if sl == 'land' or sl.startswith('land '):
                return 'ที่ดินพร้อมสิ่งปลูกสร้าง' if 'building' in sl else 'ที่ดินเปล่า'
            if 'detached house' in sl or sl == 'single house' or sl == 'house':
                return 'บ้านเดี่ยว'
            if 'shophouse' in sl or 'commercial' in sl or sl == 'retail':
                return 'อาคารพาณิชย์'
            if 'apartment' in sl:
                return 'อพาร์ทเมนท์'
            if 'warehouse' in sl or 'factory' in sl:
                return 'โรงงาน/โกดัง'
            if 'home office' in sl or 'homeoffice' in sl:
                return 'โฮมออฟฟิศ'
            if 'office' in sl:
                return 'อาคารสำนักงาน'
            if 'hotel' in sl or 'resort' in sl:
                return 'โรงแรม/รีสอร์ท'
            return s

        type_lut = {t: _resolve_single_type(t) for t in u_types}
        df['ประเภททรัพย์'] = df['ประเภททรัพย์'].map(type_lut).fillna('อื่นๆ')
        
        # Resolve mixed 'อาคารพาณิชย์/โฮมออฟฟิศ' (แยกเป็น อาคารพาณิชย์ และ โฮมออฟฟิศ)
        comm_ho_mask = df['ประเภททรัพย์'].astype(str).str.contains('อาคารพาณิชย์/โฮมออฟฟิศ|โฮมออฟฟิศ/อาคารพาณิชย์', na=False)
        if comm_ho_mask.any():
            def resolve_comm_ho(row):
                title = (str(row.get('ชื่อประกาศ', '')) + ' ' + str(row.get('ชื่อโครงการ', ''))).lower()
                if any(k in title for k in ['โฮมออฟฟิศ', 'โฮมออฟฟิต', 'home office', 'homeoffice']):
                    return 'โฮมออฟฟิศ'
                return 'อาคารพาณิชย์'
            df.loc[comm_ho_mask, 'ประเภททรัพย์'] = df[comm_ho_mask].apply(resolve_comm_ho, axis=1)

        mixed_mask = df['ประเภททรัพย์'].astype(str).str.contains('บ้านเดี่ยว/ทาวน์', na=False)
        if mixed_mask.any():
            def resolve_row(row):
                title = (str(row.get('ชื่อประกาศ', '')) + ' ' + str(row.get('ชื่อโครงการ', ''))).lower()
                if any(k in title for k in ['ตึกแถว', 'อาคารพาณิชย์', 'shophouse', 'พาณิชย์']):
                    return 'อาคารพาณิชย์'
                if any(k in title for k in ['โฮมออฟฟิศ', 'โฮมออฟฟิต', 'home office', 'homeoffice']):
                    return 'โฮมออฟฟิศ'
                if any(k in title for k in ['สำนักงาน', 'office']):
                    return 'อาคารสำนักงาน'
                if any(k in title for k in ['โกดัง', 'โรงงาน', 'warehouse', 'factory']):
                    return 'โรงงาน/โกดัง'
                if any(k in title for k in ['ทาวน์โฮม', 'ทาวน์เฮ้าส์', 'ทาวน์เฮาส์', 'townhome', 'townhouse', 'ทาวน์']):
                    return 'ทาวน์เฮ้าส์'
                if any(k in title for k in ['ที่ดิน', 'land']):
                    return 'ที่ดินเปล่า'
                if any(k in title for k in ['คอนโด', 'ห้องชุด', 'condo']):
                    return 'ห้องชุดพักอาศัย'
                return 'บ้านเดี่ยว'
            df.loc[mixed_mask, 'ประเภททรัพย์'] = df[mixed_mask].apply(resolve_row, axis=1)

    if 'ประเภทการขาย' in df.columns:
        df = df[~df['ประเภทการขาย'].astype(str).str.strip().isin(['ให้เช่า', 'เช่า'])]
        df = df[~df['ประเภทการขาย'].astype(str).str.contains('NPL', case=False, na=False)]
        sale_map = SALE_TYPE_MAPPING
        u_sales = df['ประเภทการขาย'].dropna().unique()
        sale_lut = {s: sale_map.get(str(s).strip(), str(s).strip()) for s in u_sales}
        df['ประเภทการขาย'] = df['ประเภทการขาย'].map(sale_lut).fillna('ขาย')

    if 'is_centroid' in df.columns:
        if not pd.api.types.is_bool_dtype(df['is_centroid'].dtype):
            df['is_centroid'] = df['is_centroid'].apply(is_true_centroid).astype(bool)
        else:
            df['is_centroid'] = df['is_centroid'].fillna(False).astype(bool)
    elif 'ละติจูด' in df.columns and 'ลองจิจูด' in df.columns:
        try:
            from clean_location_util import get_known_centroids_set
            known_cset = get_known_centroids_set()
            if known_cset:
                lat_n = pd.to_numeric(df['ละติจูด'], errors='coerce')
                lon_n = pd.to_numeric(df['ลองจิจูด'], errors='coerce')
                c_keys = lat_n.round(5).astype(str) + ',' + lon_n.round(5).astype(str)
                df['is_centroid'] = c_keys.isin(known_cset).fillna(False).astype(bool)
            else:
                df['is_centroid'] = False
        except Exception:
            df['is_centroid'] = False
    else:
        df['is_centroid'] = False

    if 'ชื่อโครงการ' in df.columns:
        # Respect already-cleaned projects (e.g. from convert_csv_to_parquet.py) to avoid double-cleaning with empty context
        already_proj_cleaned = bool(df.attrs.get('_project_already_cleaned', False))
        if not already_proj_cleaned:
            u_proj = df['ชื่อโครงการ'].dropna().unique()
            cache_path = os.path.join(_ROOT_DIR, "data", "project_name_clean_cache.parquet")
            proj_cache = {}
            with _PROJ_CACHE_LOCK:
                if os.path.exists(cache_path):
                    try:
                        c_df = pd.read_parquet(cache_path)
                        proj_cache = dict(zip(c_df['raw_project'].astype(str), c_df['clean_project']))
                    except Exception:
                        pass

                p_lut = {}
                missing = []
                for p in u_proj:
                    ps = str(p)
                    if ps in proj_cache:
                        p_lut[p] = proj_cache[ps]
                    else:
                        cleaned = clean_project_name(p)
                        p_lut[p] = cleaned
                        proj_cache[ps] = cleaned
                        missing.append((ps, cleaned))

                if missing:
                    try:
                        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                        updated_cache = pd.DataFrame(list(proj_cache.items()), columns=['raw_project', 'clean_project'])
                        tmp_cache_path = f"{cache_path}.tmp.{os.getpid()}.{threading.get_ident()}"
                        updated_cache.to_parquet(tmp_cache_path, compression='zstd', index=False)
                        os.replace(tmp_cache_path, cache_path)
                    except Exception:
                        try:
                            if 'tmp_cache_path' in locals() and os.path.exists(tmp_cache_path):
                                os.remove(tmp_cache_path)
                        except Exception:
                            pass

            df['ชื่อโครงการ'] = df['ชื่อโครงการ'].map(p_lut)

    if 'ชื่อประกาศ' not in df.columns:
        if 'ชื่อโครงการ' in df.columns:
            df['ชื่อประกาศ'] = df['ชื่อโครงการ'].fillna('ไม่มีชื่อ').astype(str)
        elif 'รหัสทรัพย์' in df.columns:
            df['ชื่อประกาศ'] = df['รหัสทรัพย์'].fillna('ทรัพย์สิน NPA').astype(str)
        else:
            df['ชื่อประกาศ'] = 'ทรัพย์สิน NPA'
    else:
        df['ชื่อประกาศ'] = df['ชื่อประกาศ'].fillna('ไม่มีชื่อ').astype(str)

    if 'ลิงก์' not in df.columns:
        df['ลิงก์'] = ""
    else:
        df['ลิงก์'] = df['ลิงก์'].astype(object).fillna("").astype(str)

    # Ensure LED & LED Legal property codes are uniquely formatted as <lawsuit>_<จังหวัด>
    if 'บริษัท' in df.columns and 'รหัสทรัพย์' in df.columns and 'จังหวัด' in df.columns:
        led_code_mask = df['บริษัท'].astype(str).str.startswith('LED')
        if led_code_mask.any():
            def _format_led_prop_code(code_val, prov_val):
                c = str(code_val).strip() if pd.notna(code_val) else ""
                p = str(prov_val).strip() if pd.notna(prov_val) else ""
                base_c = re.sub(r'_[^_]+$', '', c).strip()
                if not base_c or base_c in ['nan', 'None', '-']:
                    return c
                if not p or p in ['nan', 'None', '-']:
                    return base_c
                return f"{base_c}_{p}"

            df.loc[led_code_mask, 'รหัสทรัพย์'] = [
                _format_led_prop_code(c, p)
                for c, p in zip(df.loc[led_code_mask, 'รหัสทรัพย์'], df.loc[led_code_mask, 'จังหวัด'])
            ]

    # Ensure LED links use the smart lawsuit Auto-POST bridge
    if 'บริษัท' in df.columns and 'รหัสทรัพย์' in df.columns:
        led_mask = (df['บริษัท'] == 'LED')
        if led_mask.any():
            codes_s = df.loc[led_mask, 'รหัสทรัพย์'].fillna('').astype(str)
            courts_s = df.loc[led_mask, 'ศาล'].fillna('').astype(str) if 'ศาล' in df.columns else pd.Series('', index=codes_s.index)
            plaintiffs_s = df.loc[led_mask, 'โจทก์'].fillna('').astype(str) if 'โจทก์' in df.columns else pd.Series('', index=codes_s.index)

            def _build_led_url(code, court, plaintiff):
                s = str(code).strip()
                if not s or s in ['nan', 'None', '-']:
                    return "https://asset.led.go.th/newbidreg/asset_search_law_suit.asp"
                s_pure = re.sub(r'_[^_]+$', '', s).strip()
                if '/' in s_pure:
                    parts = s_pure.split('/', 1)
                    s_no, s_yr = parts[0].strip(), parts[1].strip()
                    base_u = f"/app/static/led_bridge.html?suit_no={urllib.parse.quote(s_no)}&suit_year={urllib.parse.quote(s_yr)}"
                else:
                    base_u = f"/app/static/led_bridge.html?suit_no={urllib.parse.quote(s_pure)}"
                p_raw = str(plaintiff).strip()
                if p_raw and p_raw not in ['nan', 'None', 'null', '<NA>', 'NaN', '-']:
                    try:
                        from clean_location_util import clean_plaintiff_name
                        p_clean = clean_plaintiff_name(p_raw)
                    except ImportError:
                        p_clean = p_raw
                    p_search = re.sub(r'\s*\(.*$', '', p_clean).strip()
                    if p_search:
                        base_u += f"&person1={urllib.parse.quote(p_search)}"
                c_raw = str(court).strip()
                if c_raw and c_raw not in ['nan', 'None', 'null', '<NA>', 'NaN', '-']:
                    base_u += f"&court={urllib.parse.quote(c_raw)}"
                return base_u

            df.loc[led_mask, 'ลิงก์'] = [
                _build_led_url(c, ct, p)
                for c, ct, p in zip(codes_s, courts_s, plaintiffs_s)
            ]

        # For LED Legal: use dedicated led_legal_bridge.html targeting reports.asp with only lawsuit and year
        legal_mask = df['บริษัท'].astype(str).str.strip().str.upper().isin(['LED LEGAL', 'LED_LEGAL', 'LED_SOLD'])
        if legal_mask.any():
            codes_legal = df.loc[legal_mask, 'รหัสทรัพย์'].fillna('').astype(str)

            def _build_led_legal_url(code):
                s = str(code).strip()
                if not s or s in ['nan', 'None', '-']:
                    return "https://asset.led.go.th/report/reports.asp"
                s_pure = re.sub(r'_[^_]+$', '', s).strip()
                if '/' in s_pure:
                    parts = s_pure.split('/', 1)
                    s_no, s_yr = parts[0].strip(), parts[1].strip()
                    return f"/app/static/led_legal_bridge.html?suit_no={urllib.parse.quote(s_no)}&suit_year={urllib.parse.quote(s_yr)}"
                return f"/app/static/led_legal_bridge.html?suit_no={urllib.parse.quote(s_pure)}"

            df.loc[legal_mask, 'ลิงก์'] = [
                _build_led_legal_url(c)
                for c in codes_legal
            ]

    if 'ราคา' in df.columns:
        df['ราคา'] = pd.to_numeric(df['ราคา'], errors='coerce')
        df.loc[df['ราคา'] < 1000, 'ราคา'] = np.nan
    else:
        df['ราคา'] = np.nan

    for _area_c in ('เนื้อที่ (ตร.ว.)', 'เนื้อที่ (ไร่-งาน-ตร.ว.)', 'พื้นที่ (ไร่-งาน-วา)'):
        if _area_c in df.columns:
            df[_area_c] = (
                df[_area_c]
                .astype(str)
                .str.strip()
                .str.replace(r'^="(.*)"$', r'\1', regex=True)
                .replace({'nan': None, 'None': None, '<NA>': None, '': None})
            )
    if 'เนื้อที่ (ตร.ว.)' not in df.columns and 'เนื้อที่ (ไร่-งาน-ตร.ว.)' in df.columns:
        df['เนื้อที่ (ตร.ว.)'] = df['เนื้อที่ (ไร่-งาน-ตร.ว.)']

    if 'พื้นที่_ตารางวา' not in df.columns:
        if 'เนื้อที่_ตารางวา' in df.columns:
            df['พื้นที่_ตารางวา'] = pd.to_numeric(df['เนื้อที่_ตารางวา'], errors='coerce')
        elif 'เนื้อที่ (ตร.ว.)' in df.columns:
            df['พื้นที่_ตารางวา'] = df['เนื้อที่ (ตร.ว.)'].apply(parse_area_to_sqwah)
        elif 'เนื้อที่ (ไร่-งาน-ตร.ว.)' in df.columns:
            df['พื้นที่_ตารางวา'] = df['เนื้อที่ (ไร่-งาน-ตร.ว.)'].apply(parse_area_to_sqwah)
        elif 'พื้นที่ (ไร่-งาน-วา)' in df.columns:
            df['พื้นที่_ตารางวา'] = df['พื้นที่ (ไร่-งาน-วา)'].apply(parse_area_to_sqwah)
        else:
            df['พื้นที่_ตารางวา'] = np.nan
    else:
        df['พื้นที่_ตารางวา'] = pd.to_numeric(df['พื้นที่_ตารางวา'], errors='coerce')

    if 'พื้นที่ใช้สอย (ตร.ม.)' not in df.columns:
        df['พื้นที่ใช้สอย (ตร.ม.)'] = np.nan
    else:
        df['พื้นที่ใช้สอย (ตร.ม.)'] = pd.to_numeric(df['พื้นที่ใช้สอย (ตร.ม.)'], errors='coerce')
        bad_area_mask = (df['ราคา'] > 10000) & (df['พื้นที่ใช้สอย (ตร.ม.)'] == df['ราคา'])
        if 'ประเภททรัพย์' in df.columns:
            bad_area_mask |= (df['ประเภททรัพย์'].isin(['คอนโด', 'คอนโดมิเนียม', 'ห้องชุด', 'ห้องชุดพักอาศัย', 'ทาวน์เฮ้าส์', 'ทาวน์โฮม']) & (df['พื้นที่ใช้สอย (ตร.ม.)'] > 5000))
        df.loc[bad_area_mask, 'พื้นที่ใช้สอย (ตร.ม.)'] = np.nan

    if 'ราคาต่อตารางวา' not in df.columns:
        df['ราคาต่อตารางวา'] = np.where((df['พื้นที่_ตารางวา'] > 0) & (df['ราคา'] > 0), df['ราคา'] / df['พื้นที่_ตารางวา'], np.nan)
    else:
        df['ราคาต่อตารางวา'] = pd.to_numeric(df['ราคาต่อตารางวา'], errors='coerce')
        missing_puw = df['ราคาต่อตารางวา'].isna() & (df['พื้นที่_ตารางวา'] > 0) & (df['ราคา'] > 0)
        if missing_puw.any():
            df.loc[missing_puw, 'ราคาต่อตารางวา'] = df.loc[missing_puw, 'ราคา'] / df.loc[missing_puw, 'พื้นที่_ตารางวา']

    if 'ราคาต่อตารางเมตร' not in df.columns:
        df['ราคาต่อตารางเมตร'] = np.where((df['พื้นที่ใช้สอย (ตร.ม.)'] > 0) & (df['ราคา'] > 0), df['ราคา'] / df['พื้นที่ใช้สอย (ตร.ม.)'], np.nan)
    else:
        df['ราคาต่อตารางเมตร'] = pd.to_numeric(df['ราคาต่อตารางเมตร'], errors='coerce')
        missing_pum = df['ราคาต่อตารางเมตร'].isna() & (df['พื้นที่ใช้สอย (ตร.ม.)'] > 0) & (df['ราคา'] > 0)
        if missing_pum.any():
            df.loc[missing_pum, 'ราคาต่อตารางเมตร'] = df.loc[missing_pum, 'ราคา'] / df.loc[missing_pum, 'พื้นที่ใช้สอย (ตร.ม.)']

    if 'จังหวัด' in df.columns:
        def _clean_prov_val(v):
            if pd.isna(v):
                return np.nan
            s = str(v).strip().strip(" ,;.-'\"/\\")
            s = re.sub(r'^(จ\.|จังหวัด)\s*', '', s).strip()
            if s in ['กทม', 'กทม.', 'กรุงเทพ', 'กรุงเทพฯ']:
                s = 'กรุงเทพมหานคร'
            elif s in ['อยุธยา']:
                s = 'พระนครศรีอยุธยา'
            if s in ['', '-', 'nan', 'None', '<NA>', 'ไม่มีข้อมูล']:
                return np.nan
            if re.search(r'\d', s) or not re.search(r'^[ก-๙]', s):
                return np.nan
            return s

        df['จังหวัด'] = df['จังหวัด'].apply(_clean_prov_val)
        df['ภาค'] = df['จังหวัด'].map(PROVINCE_TO_REGION).fillna('อื่นๆ / ไม่ระบุ')

    if 'ชั้น' not in df.columns:
        df['ชั้น'] = None
    else:
        df['ชั้น'] = df['ชั้น'].replace({'nan': None, 'None': None, 'null': None, '<NA>': None, 'NaN': None, '-': None, '': None})

    if 'เลขโฉนด' not in df.columns:
        df['เลขโฉนด'] = None
    else:
        df['เลขโฉนด'] = df['เลขโฉนด'].replace({'nan': None, 'None': None, 'null': None, '<NA>': None, 'NaN': None, '-': None, '': None})

    if 'โจทก์' not in df.columns:
        df['โจทก์'] = None
    else:
        df['โจทก์'] = df['โจทก์'].replace({'nan': None, 'None': None, 'null': None, '<NA>': None, 'NaN': None, '-': None, '': None})
        try:
            from clean_location_util import clean_plaintiff_name
            df['โจทก์'] = df['โจทก์'].apply(lambda x: clean_plaintiff_name(x) if x else None)
        except ImportError:
            pass

    if 'ยอดเข้าชม' not in df.columns:
        df['ยอดเข้าชม'] = None
    else:
        df['ยอดเข้าชม'] = pd.to_numeric(df['ยอดเข้าชม'], errors='coerce').astype('Int32')

    if 'ยอดคลิก' not in df.columns:
        df['ยอดคลิก'] = None
    else:
        df['ยอดคลิก'] = pd.to_numeric(df['ยอดคลิก'], errors='coerce').astype('Int32')

    if 'อำเภอ' in df.columns:
        s_amp = df['อำเภอ'].astype(object).where(df['อำเภอ'].notna(), '').astype(str).str.strip().str.strip(" ,;.-'\"/\\")
        s_amp = s_amp.replace({'nan': '', 'None': '', '<NA>': '', 'NaN': '', '-': '', 'ไม่มีข้อมูล': ''})
        en_amp_mask = (s_amp != '') & s_amp.str.contains(r'[a-zA-Z]', regex=True, na=False)
        if en_amp_mask.any():
            def _safe_clean_amp(val):
                res = translate_amphoe_en_to_th(val)
                return res if re.match(r'^[ก-๙]', str(res or '')) else 'ไม่มีข้อมูล'
            s_amp.loc[en_amp_mask] = s_amp.loc[en_amp_mask].apply(_safe_clean_amp)
        df['อำเภอ'] = s_amp.replace({'': np.nan})

    if 'ตำบล' in df.columns:
        s_tam = df['ตำบล'].astype(object).where(df['ตำบล'].notna(), '').astype(str).str.strip().str.strip(" ,;.-'\"/\\")
        s_tam = s_tam.replace({'nan': '', 'None': '', '<NA>': '', 'NaN': '', '-': '', 'ไม่มีข้อมูล': ''})
        en_tam_mask = (s_tam != '') & s_tam.str.contains(r'[a-zA-Z]', regex=True, na=False)
        if en_tam_mask.any():
            s_tam.loc[en_tam_mask] = s_tam.loc[en_tam_mask].apply(
                lambda s: re.sub(r'[a-zA-Z\(\)\[\]]+', '', str(s)).strip() if re.search(r'[ก-๙]', str(s)) else 'ไม่มีข้อมูล'
            )
        df['ตำบล'] = s_tam.replace({'': np.nan})

    # Pre-clean normalized project name for ultra-fast competitor matching
    if 'norm_project_name' not in df.columns or (len(df) > 0 and not bool(df['_is_derived_clean'].fillna(False).all() if '_is_derived_clean' in df.columns else False)):
        if 'ชื่อโครงการ' in df.columns:
            u_projs = df['ชื่อโครงการ'].dropna().unique()
            norm_map = {p: normalize_project_name(p) for p in u_projs if p}
            df['norm_project_name'] = df['ชื่อโครงการ'].map(norm_map).fillna('')
        else:
            df['norm_project_name'] = ''

    # Preserve float64 for high-value prices (>16.77M Baht), 5-6 decimal coordinates, areas, and unit rates
    for f64_col in ['ราคา', 'ราคาขายได้', 'ละติจูด', 'ลองจิจูด', 'พื้นที่_ตารางวา', 'พื้นที่ใช้สอย (ตร.ม.)', 'ราคาต่อตารางวา', 'ราคาต่อตารางเมตร']:
        if f64_col in df.columns:
            df[f64_col] = pd.to_numeric(df[f64_col], errors='coerce').astype('float64')

    # Convert repeated string columns to category for 5x faster filtering and 70% less RAM
    for col in ['บริษัท', 'ประเภททรัพย์', 'จังหวัด', 'ภาค', 'ประเภทการขาย', 'อำเภอ', 'ตำบล']:
        if col in df.columns:
            df[col] = df[col].astype('category')

    df = _apply_led_legal_sold_prices(df)
    df['_is_derived_clean'] = True
    return df
