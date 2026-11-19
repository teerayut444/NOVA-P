import os
import sys
import json
import re
import threading
import pandas as pd

_GIS_LOCK = threading.RLock()

# --- English to Thai District (Amphoe) Translation Mapping ---
_GIS_AMP_EN_TO_TH = None

def get_amp_en_to_th():
    global _GIS_AMP_EN_TO_TH
    if _GIS_AMP_EN_TO_TH is not None:
        return _GIS_AMP_EN_TO_TH
    
    with _GIS_LOCK:
        if _GIS_AMP_EN_TO_TH is not None:
            return _GIS_AMP_EN_TO_TH
        mapping = {}
        try:
            import os, sys, json
            candidates = []
            if getattr(sys, '_MEIPASS', None):
                candidates.append(os.path.join(sys._MEIPASS, "districts.geojson"))
                candidates.append(os.path.join(sys._MEIPASS, "subdistricts.geojson"))
            base_dir = os.path.dirname(os.path.abspath(__file__))
            candidates.append(os.path.join(base_dir, "districts.geojson"))
            candidates.append(os.path.join(os.path.dirname(base_dir), "districts.geojson"))
            candidates.append(os.path.join(os.path.dirname(base_dir), "data", "districts.geojson"))
            candidates.append(os.path.join(base_dir, "subdistricts.geojson"))
            candidates.append(os.path.join(os.path.dirname(base_dir), "subdistricts.geojson"))
            candidates.append(os.path.join(os.path.dirname(base_dir), "data", "subdistricts.geojson"))
            
            geojson_path = next((p for p in candidates if os.path.exists(p)), None)
            if geojson_path:
                with open(geojson_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for feat in data.get("features", []):
                    p = feat.get("properties", {})
                    th = str(p.get("amp_th") or "").strip()
                    en = str(p.get("amp_en") or "").strip()
                    if th and en:
                        k = re.sub(r'[^a-zA-Z0-9]', '', en).lower()
                        mapping[k] = th
                        if en.lower().startswith('mueang '):
                            base_en = re.sub(r'[^a-zA-Z0-9]', '', en[7:]).lower()
                            if base_en not in mapping:
                                mapping[base_en] = th
        except Exception:
            pass
            
        _GIS_AMP_EN_TO_TH = mapping
        return _GIS_AMP_EN_TO_TH

def translate_amphoe_en_to_th(val):
    """
    Translates an English amphoe name or removes English characters:
    - If matches known district in districts.geojson (e.g. 'Si Racha' -> 'ศรีราชา', 'Muang Chiang Mai' -> 'เมืองเชียงใหม่')
    - If bilingual with Thai text (e.g. 'ปทุมธานี (Mueang)', 'ศรีราชา / Si Racha') -> strips English, returns Thai part
    - If unmapped pure English junk (e.g. 'EEC', 'free', 'https', 'A', 'Directions') -> returns "" (strictly NO English)
    """
    if not val or pd.isna(val):
        return ""
    s = str(val).strip()
    if not re.search(r'[a-zA-Z]', s):
        return s
        
    amp_map = get_amp_en_to_th()
    
    # 1. Full string or normalized key lookup
    s_clean = re.sub(r'^(?:amphoe|amphur|khet|district)\s+', '', s, flags=re.I).strip()
    s_norm = re.sub(r'^muang\s+', 'mueang', s_clean, flags=re.I)
    k = re.sub(r'[^a-zA-Z0-9]', '', s_norm).lower()
    if k in amp_map:
        return amp_map[k]
        
    # 2. Check embedded English word inside parentheses/brackets (must contain [a-zA-Z])
    m_en = re.search(r'([a-zA-Z]+(?:[\s\-]+[a-zA-Z]+)*)', s)
    if m_en:
        sub_k = re.sub(r'^(?:amphoe|amphur|khet|district)\s+', '', m_en.group(1), flags=re.I).strip()
        sub_norm = re.sub(r'^muang\s+', 'mueang', sub_k, flags=re.I)
        sub_key = re.sub(r'[^a-zA-Z0-9]', '', sub_norm).lower()
        if sub_key in amp_map:
            return amp_map[sub_key]
            
    # 3. If Thai characters exist in the string, strip all English letters, parentheses, and outer symbols (preserve Thai internal hyphens like สุไหงโก-ลก)
    if re.search(r'[ก-๙]', s):
        s_th = re.sub(r'[a-zA-Z]', '', s)
        s_th = re.sub(r'[\(\[\{][^\)\]\}]*[\)\]\}]', '', s_th)
        s_th = re.sub(r'[\(\[\{\)\]\}\/\\_:,.]+', ' ', s_th)
        s_th = re.sub(r'^[\s\-]+|[\s\-]+$', '', s_th)
        s_th = re.sub(r'\s+', ' ', s_th).strip()
        if re.search(r'[ก-๙]', s_th):
            return s_th
            
    # 4. Pure English junk that cannot be mapped -> return empty string (STRICTLY NO ENGLISH)
    return ""

# Official administrative names that must not be stripped by junk regexes (even before GIS loads)
_OFFICIAL_NAME_KEEP = frozenset({
    "เกษตรวิสัย", "กันตรวจระมวล", "ตรวจ", "ตรมไพร",
    "ถนน", "ถนนนครไชยศรี", "ถนนพญาไท", "ถนนเพชรบุรี",
    "ถนนใหญ่", "ถนนโพธิ์", "ถนนหัก", "ถนนขาด",
    "ไร่", "จ.ป.ร.",
})

# Pre-compiled junk patterns at module level for performance
_COMPILED_JUNK_PATTERNS = [
    re.compile(jp) for jp in [
        r'รวมประกาศ', r'^ประกาศ', r'^ขาย', r'^เช่า', r'^โครงการ', 
        r'^แผนที่', r'^ซอย', r'^ซ\.', r'^ถนน', r'^ถ\.', r'^หมู่บ้าน',
        r'ห้องนอน', r'ห้องน้ำ', r'ที่จอดรถ', r'^\d+\s*ไร่', r'^ไร่$',
        r'(?:^|\d|\s)ตร\.?\s*ว\.?(?=$|\s|\d)', r'ตารางวา',
        r'(?:^|\d|\s)ตร\.?\s*ม\.?(?=$|\s|\d)', r'ตารางเมตร', r'ชั้น\s*\d+',
        r'มิวนีค', r'^\d+$', r'^\d+[\)\.]?$',
        r'ผังเมือง', r'พื้นที่สี', r'ชุมชน', r'ทางกว้าง', r'นิคมอุตสาหกรรม', r'ป่าสงวน', r'อุตสาหกรรม',
        r'การนิคม', r'การศึกษา', r'การให้บริการ', r'ขอใบรง', r'จริงตามภาพ', r'ติดต่อ', r'ด้านข้าง'
    ]
]

def clean_location_field(val, is_amphoe=False, field_type=None):
    """
    Cleans subdistrict (ตำบล) and district (อำเภอ) fields:
    - Removes zero-width spaces, quotes, leading/trailing punctuation (*, -, _, ., :, >, /, #, @, etc.)
    - Removes leading parenthesized prefixes e.g. (เมืองไผ่) บ้านใหม่ -> บ้านใหม่
    - Clears invalid junk strings (e.g. '> รวมประกาศขาย', 'โครงการ', 'ขาย', 'เช่า', 'แผนที่', 'ซอย', 'ถนน', 'ห้องนอน', 'ไร่', etc.)
    - Clears numeric values or strings starting with digits
    - Removes administrative prefixes (ตำบล, แขวง, กิ่งอำเภอ, อำเภอ, เขต, จังหวัด)
    - Maps English district names to official Thai names
    - Enforces 100% Thai names: strictly NO English characters [a-zA-Z] allowed in output!
    """
    if field_type is not None:
        is_amphoe = (str(field_type).strip().lower() in ("amphoe", "district", "อำเภอ", "เขต", "true", "1")) or bool(is_amphoe)
    if not val or pd.isna(val) or str(val).strip().lower() in ["nan", "none", "null", "undefined", "-", "อื่นๆ", ""]:
        return ""
    s = str(val).strip()
    
    # Remove zero-width spaces and quotes
    s = s.replace('\u200b', '').replace('"', '').replace("'", '').strip()
    
    # For Amphoe: if English text is inside parentheses (e.g. 'อ. (Si Racha)' or '(Si Racha)'),
    # allow translate_amphoe_en_to_th to extract/translate it before stripping parentheses.
    if is_amphoe and re.search(r'[\(\[\{][^)\]\}]*[a-zA-Z]', s):
        outside_th = re.sub(r'[\(\[\{][^\)\]\}]*[\)\]\}]', '', s)
        outside_th = re.sub(r'[\(\[\{].*$', '', outside_th)
        outside_th = re.sub(r'^(?:กิ่งอำเภอ|อำเภอ|เขต|ตำบล|จังหวัด|อ\.|ข\.|ต\.|จ\.)\s*', '', outside_th).strip()
        if not re.search(r'[ก-๙]{2,}', outside_th):
            s_pre = re.sub(r'^(?:กิ่งอำเภอ|อำเภอ|เขต|ตำบล|จังหวัด|อ\.|ข\.|ต\.|จ\.)\s*', '', s).strip()
            s_tr = translate_amphoe_en_to_th(s_pre)
            if s_tr:
                s = s_tr

    # Remove leading parenthesized/bracketed prefixes
    s = re.sub(r'^\([^\)]*\)\s*', '', s).strip()
    s = re.sub(r'^\[[^\]]*\]\s*', '', s).strip()
    
    # Remove trailing parenthesized/bracketed suffixes or unclosed brackets e.g. ปทุมธานี(ธัญบุรี) -> ปทุมธานี, ธัญบุรี(กลางเมือง -> ธัญบุรี
    s = re.sub(r'[\(\[\{].*$', '', s).strip()
    
    # Remove leading/trailing junk/symbols (preserve valid Thai abbr. like จ.ป.ร.)
    s = re.sub(r'^[>\/\*\-_\.:#@\s\(\)\[\]]+', '', s).strip()
    if s not in _OFFICIAL_NAME_KEEP:
        s = re.sub(r'[>\/\*\-_\.:#@\s\(\)\[\]]+$', '', s).strip()
    
    # Preserve exact official place names before checking generic junk patterns
    is_official_name = (
        s in _OFFICIAL_NAME_KEEP
        or (_GIS_AMP_TO_PROV and s in _GIS_AMP_TO_PROV)
        or (_GIS_TAM_TO_AMP_PROV and s in _GIS_TAM_TO_AMP_PROV)
    )
    if not is_official_name:
        for jp in _COMPILED_JUNK_PATTERNS:
            if jp.search(s):
                return ""
            
    # For Amphoe: if contains numbers or road codes, clear
    if is_amphoe:
        if re.search(r'\d', s):
            return ""
        # Clean redundant prefixes: กิ่งอำเภอ, อำเภอ, เขต, ตำบล, จังหวัด, อ., ข.
        s = re.sub(r'^(?:กิ่งอำเภอ|อำเภอ|เขต|ตำบล|จังหวัด|อ\.|ข\.)\s*', '', s).strip()
        # Translate or remove English names
        if re.search(r'[a-zA-Z]', s):
            s = translate_amphoe_en_to_th(s)
        # If amphoe is <= 2 chars and not in the only 3 valid 2-letter amphoes in Thailand ("คง", "ปง", "พล")
        if len(s) <= 2 and s not in ["คง", "ปง", "พล"]:
            return ""
    else:
        # For Subdistrict: clean redundant prefixes: ตำบล, แขวง
        if s in SPECIAL_TAM_CLEAN:
            s = SPECIAL_TAM_CLEAN[s]
        if re.match(r'^(?:เขต|อำเภอ|กิ่งอำเภอ|จังหวัด)', s) or re.match(r'^(?:เขต|อำเภอ|กิ่งอำเภอ|จังหวัด|ตำบล|แขวง)$', s):
            return ""
        s = re.sub(r'^(?:ตำบล|แขวง)\s*', '', s).strip()
        if re.match(r'^\d', s):
            return ""
        # If contains English, strip English letters
        if re.search(r'[a-zA-Z]', s):
            if re.search(r'[ก-๙]', s):
                s = re.sub(r'[a-zA-Z]', '', s)
                s = re.sub(r'[\(\[\{][^\)\]\}]*[\)\]\}]', '', s).strip()
                s = re.sub(r'[\(\[\{\)\]\}\/\\\-_:,.]+', ' ', s).strip()
            else:
                return ""
            
    # Strictly must start with a valid Thai letter [ก-๙] - NO English allowed!
    if not re.match(r'^[ก-๙]', s):
        return ""
        
    return s

# --- Offline In-Memory GIS Engine (Shapely STRtree) ---
_GIS_TREE = None
_GIS_GEOMS = []
_GIS_PROPS = None
_GIS_CENTROIDS = None
_GIS_TAM_PROV = None
_GIS_AMP_PROV = None
_GIS_DIST_CENTROIDS = None
_GIS_ALL_PROVINCES = None
_GIS_SORTED_PROVINCES = None
_GIS_AMP_TO_PROV = None
_GIS_TAM_TO_AMP_PROV = None
_GIS_GEOM_MAP = {}
_GIS_INIT_TRIED = False

SPECIAL_TAM_CLEAN = {
    'เทศบาลนครสมุทรปร': 'ปากน้ำ',
    'เทศบาลบางปู': 'บางปูใหม่',
    'เทศบาลบางเมือง': 'บางเมือง',
    'เทศบาลเมืองพระปร': 'ตลาด',
    'เทศบาลสำโรงใต้': 'สำโรงใต้',
    'เขตการปกคองพิเศษ': 'เมืองพัทยา',
    'ท่าเรือ (เทศบาลเมื': 'ท่าเรือ',
    'เทศบาลเมืองทุ่งส': 'ปากแพรก'
}

POPULAR_ZONE_MAPPING = {
    'พัทยา': {'ตำบล': 'เมืองพัทยา', 'อำเภอ': 'บางละมุง', 'จังหวัด': 'ชลบุรี'},
    'เมืองพัทยา': {'ตำบล': 'เมืองพัทยา', 'อำเภอ': 'บางละมุง', 'จังหวัด': 'ชลบุรี'},
    'บางแสน': {'ตำบล': 'แสนสุข', 'อำเภอ': 'เมืองชลบุรี', 'จังหวัด': 'ชลบุรี'},
    'หาดบางแสน': {'ตำบล': 'แสนสุข', 'อำเภอ': 'เมืองชลบุรี', 'จังหวัด': 'ชลบุรี'},
    'เขาใหญ่': {'ตำบล': 'หมูสี', 'อำเภอ': 'ปากช่อง', 'จังหวัด': 'นครราชสีมา'},
    'ปากช่อง-เขาใหญ่': {'ตำบล': 'หมูสี', 'อำเภอ': 'ปากช่อง', 'จังหวัด': 'นครราชสีมา'},
    'หัวหิน': {'ตำบล': 'หัวหิน', 'อำเภอ': 'หัวหิน', 'จังหวัด': 'ประจวบคีรีขันธ์'},
    'ชะอำ': {'ตำบล': 'ชะอำ', 'อำเภอ': 'ชะอำ', 'จังหวัด': 'เพชรบุรี'},
    'อโศก': {'ตำบล': 'คลองเตยเหนือ', 'อำเภอ': 'วัฒนา', 'จังหวัด': 'กรุงเทพมหานคร'},
    'ทองหล่อ': {'ตำบล': 'คลองตันเหนือ', 'อำเภอ': 'วัฒนา', 'จังหวัด': 'กรุงเทพมหานคร'},
    'เอกมัย': {'ตำบล': 'คลองตันเหนือ', 'อำเภอ': 'วัฒนา', 'จังหวัด': 'กรุงเทพมหานคร'},
    'พร้อมพงษ์': {'ตำบล': 'คลองตัน', 'อำเภอ': 'คลองเตย', 'จังหวัด': 'กรุงเทพมหานคร'},
    'อ่อนนุช': {'ตำบล': 'พระโขนงเหนือ', 'อำเภอ': 'วัฒนา', 'จังหวัด': 'กรุงเทพมหานคร'},
    'อุดมสุข': {'ตำบล': 'บางนาเหนือ', 'อำเภอ': 'บางนา', 'จังหวัด': 'กรุงเทพมหานคร'},
    'วัชรพล': {'ตำบล': 'ท่าแร้ง', 'อำเภอ': 'บางเขน', 'จังหวัด': 'กรุงเทพมหานคร'},
    'เมืองทอง': {'ตำบล': 'บ้านใหม่', 'อำเภอ': 'ปากเกร็ด', 'จังหวัด': 'นนทบุรี'},
    'เมืองทองธานี': {'ตำบล': 'บ้านใหม่', 'อำเภอ': 'ปากเกร็ด', 'จังหวัด': 'นนทบุรี'},
    'รัชดา': {'ตำบล': 'ห้วยขวาง', 'อำเภอ': 'ห้วยขวาง', 'จังหวัด': 'กรุงเทพมหานคร'},
    'รัชดาภิเษก': {'ตำบล': 'ห้วยขวาง', 'อำเภอ': 'ห้วยขวาง', 'จังหวัด': 'กรุงเทพมหานคร'},
    'พระราม 9': {'ตำบล': 'ห้วยขวาง', 'อำเภอ': 'ห้วยขวาง', 'จังหวัด': 'กรุงเทพมหานคร'},
    'พระราม9': {'ตำบล': 'ห้วยขวาง', 'อำเภอ': 'ห้วยขวาง', 'จังหวัด': 'กรุงเทพมหานคร'},
    'พระราม 2': {'ตำบล': 'แสมดำ', 'อำเภอ': 'บางขุนเทียน', 'จังหวัด': 'กรุงเทพมหานคร'},
    'พระราม 3': {'ตำบล': 'บางโพงพาง', 'อำเภอ': 'ยานนาวา', 'จังหวัด': 'กรุงเทพมหานคร'},
    'สาทร': {'ตำบล': 'ทุ่งมหาเมฆ', 'อำเภอ': 'สาทร', 'จังหวัด': 'กรุงเทพมหานคร'},
    'สีลม': {'ตำบล': 'สีลม', 'อำเภอ': 'บางรัก', 'จังหวัด': 'กรุงเทพมหานคร'},
    'ลุมพินี': {'ตำบล': 'ลุมพินี', 'อำเภอ': 'ปทุมวัน', 'จังหวัด': 'กรุงเทพมหานคร'},
    'เพลินจิต': {'ตำบล': 'ลุมพินี', 'อำเภอ': 'ปทุมวัน', 'จังหวัด': 'กรุงเทพมหานคร'},
    'ราชเทวี': {'ตำบล': 'ถนนเพชรบุรี', 'อำเภอ': 'ราชเทวี', 'จังหวัด': 'กรุงเทพมหานคร'},
    'พญาไท': {'ตำบล': 'พญาไท', 'อำเภอ': 'พญาไท', 'จังหวัด': 'กรุงเทพมหานคร'},
    'อารีย์': {'ตำบล': 'สามเสนใน', 'อำเภอ': 'พญาไท', 'จังหวัด': 'กรุงเทพมหานคร'},
    'สะพานควาย': {'ตำบล': 'สามเสนใน', 'อำเภอ': 'พญาไท', 'จังหวัด': 'กรุงเทพมหานคร'},
    'จตุจักร': {'ตำบล': 'จตุจักร', 'อำเภอ': 'จตุจักร', 'จังหวัด': 'กรุงเทพมหานคร'},
    'ลาดพร้าว': {'ตำบล': 'ลาดพร้าว', 'อำเภอ': 'ลาดพร้าว', 'จังหวัด': 'กรุงเทพมหานคร'},
    'ลาดพร้าวตอนกลาง': {'ตำบล': 'ลาดพร้าว', 'อำเภอ': 'ลาดพร้าว', 'จังหวัด': 'กรุงเทพมหานคร'},
    'โชคชัย 4': {'ตำบล': 'ลาดพร้าว', 'อำเภอ': 'ลาดพร้าว', 'จังหวัด': 'กรุงเทพมหานคร'},
    'โชคชัย': {'ตำบล': 'ลาดพร้าว', 'อำเภอ': 'ลาดพร้าว', 'จังหวัด': 'กรุงเทพมหานคร'},
    'รามคำแหง': {'ตำบล': 'หัวหมาก', 'อำเภอ': 'บางกะปิ', 'จังหวัด': 'กรุงเทพมหานคร'},
    'พัฒนาการ': {'ตำบล': 'สวนหลวง', 'อำเภอ': 'สวนหลวง', 'จังหวัด': 'กรุงเทพมหานคร'},
    'ศรีนครินทร์': {'ตำบล': 'หนองบอน', 'อำเภอ': 'ประเวศ', 'จังหวัด': 'กรุงเทพมหานคร'},
    'บางนา': {'ตำบล': 'บางนาเหนือ', 'อำเภอ': 'บางนา', 'จังหวัด': 'กรุงเทพมหานคร'},
    'เทพารักษ์': {'ตำบล': 'เทพารักษ์', 'อำเภอ': 'เมืองสมุทรปราการ', 'จังหวัด': 'สมุทรปราการ'},
    'สำโรง': {'ตำบล': 'สำโรงเหนือ', 'อำเภอ': 'เมืองสมุทรปราการ', 'จังหวัด': 'สมุทรปราการ'},
    'รังสิต': {'ตำบล': 'ประชาธิปัตย์', 'อำเภอ': 'ธัญบุรี', 'จังหวัด': 'ปทุมธานี'},
    'คลองหลวง': {'ตำบล': 'คลองหนึ่ง', 'อำเภอ': 'คลองหลวง', 'จังหวัด': 'ปทุมธานี'},
    'ศีรษะจรเข้น้อย': {'ตำบล': 'ศีรษะจรเข้น้อย', 'อำเภอ': 'บางเสาธง', 'จังหวัด': 'สมุทรปราการ'},
    'ศีรษะจรเข้ใหญ่': {'ตำบล': 'ศีรษะจรเข้ใหญ่', 'อำเภอ': 'บางเสาธง', 'จังหวัด': 'สมุทรปราการ'},
    'ศรีษะจรเข้น้อย': {'ตำบล': 'ศีรษะจรเข้น้อย', 'อำเภอ': 'บางเสาธง', 'จังหวัด': 'สมุทรปราการ'},
    'ศรีษะจรเข้ใหญ่': {'ตำบล': 'ศีรษะจรเข้ใหญ่', 'อำเภอ': 'บางเสาธง', 'จังหวัด': 'สมุทรปราการ'},
    'กรุงเทพถนนหลังสวน': {'ตำบล': 'ลุมพินี', 'อำเภอ': 'ปทุมวัน', 'จังหวัด': 'กรุงเทพมหานคร'},
    'กรุงเทพซอยต้นสน': {'ตำบล': 'ลุมพินี', 'อำเภอ': 'ปทุมวัน', 'จังหวัด': 'กรุงเทพมหานคร'},
    'กรุงเทพลาดพร้าว': {'ตำบล': 'ลาดพร้าว', 'อำเภอ': 'ลาดพร้าว', 'จังหวัด': 'กรุงเทพมหานคร'},
    'กรุงเทพสะพานสูง': {'ตำบล': 'สะพานสูง', 'อำเภอ': 'สะพานสูง', 'จังหวัด': 'กรุงเทพมหานคร'},
    'กรุงเทพถนนวิทยุ': {'ตำบล': 'ลุมพินี', 'อำเภอ': 'ปทุมวัน', 'จังหวัด': 'กรุงเทพมหานคร'},
    'กรุงเทพถนนรามอินทรา': {'ตำบล': 'ท่าแร้ง', 'อำเภอ': 'บางเขน', 'จังหวัด': 'กรุงเทพมหานคร'},
    'กรุงเทพท่าแร้ง': {'ตำบล': 'ท่าแร้ง', 'อำเภอ': 'บางเขน', 'จังหวัด': 'กรุงเทพมหานคร'},
    'กรุงเทพบางจาก': {'ตำบล': 'บางจาก', 'อำเภอ': 'พระโขนง', 'จังหวัด': 'กรุงเทพมหานคร'},
    'กรุงเทพพหลโยธิน': {'ตำบล': 'จอมพล', 'อำเภอ': 'จตุจักร', 'จังหวัด': 'กรุงเทพมหานคร'},
    'กรุงเทพถนนเพชรบุรี': {'ตำบล': 'ถนนเพชรบุรี', 'อำเภอ': 'ราชเทวี', 'จังหวัด': 'กรุงเทพมหานคร'},
    'รามอินทรา': {'ตำบล': 'ท่าแร้ง', 'อำเภอ': 'บางเขน', 'จังหวัด': 'กรุงเทพมหานคร'},
    'เกษตร-นวมินทร์': {'ตำบล': 'คลองกุ่ม', 'อำเภอ': 'บึงกุ่ม', 'จังหวัด': 'กรุงเทพมหานคร'},
    'เกษตรศาสตร์': {'ตำบล': 'ลาดยาว', 'อำเภอ': 'จตุจักร', 'จังหวัด': 'กรุงเทพมหานคร'},
    'แจ้งวัฒนะ': {'ตำบล': 'ทุ่งสองห้อง', 'อำเภอ': 'หลักสี่', 'จังหวัด': 'กรุงเทพมหานคร'},
    'ลาดพร้าวตอนปลาย': {'ตำบล': 'คลองจั่น', 'อำเภอ': 'บางกะปิ', 'จังหวัด': 'กรุงเทพมหานคร'},
    'ลาดพร้าวตอนต้น': {'ตำบล': 'จอมพล', 'อำเภอ': 'จตุจักร', 'จังหวัด': 'กรุงเทพมหานคร'},
    'รามคำแหงตอนต้น': {'ตำบล': 'หัวหมาก', 'อำเภอ': 'บางกะปิ', 'จังหวัด': 'กรุงเทพมหานคร'},
    'ราชพฤกษ์': {'ตำบล': 'บางหว้า', 'อำเภอ': 'ภาษีเจริญ', 'จังหวัด': 'กรุงเทพมหานคร'},
    'เลียบทางด่วนรามอินทรา': {'ตำบล': 'ลาดพร้าว', 'อำเภอ': 'ลาดพร้าว', 'จังหวัด': 'กรุงเทพมหานคร'},
    'นวลจันทร์': {'ตำบล': 'นวลจันทร์', 'อำเภอ': 'บึงกุ่ม', 'จังหวัด': 'กรุงเทพมหานคร'},
    'สุราษฎร์ธานีบ่อผุด': {'ตำบล': 'บ่อผุด', 'อำเภอ': 'เกาะสมุย', 'จังหวัด': 'สุราษฎร์ธานี'},
    'พระราม': {'ตำบล': 'บางโพงพาง', 'อำเภอ': 'ยานนาวา', 'จังหวัด': 'กรุงเทพมหานคร'},
}

TRUNCATED_AMPHOE_FIX = {
    'เมืองสุราษฎร์ธาน': 'เมืองสุราษฎร์ธานี',
    'เมืองนครศรีธรรมร': 'เมืองนครศรีธรรมราช',
    'เมืองประจวบคีรีข': 'เมืองประจวบคีรีขันธ์',
    'สุไหงโก-ล': 'สุไหงโก-ลก',
    'สุไหงปา': 'สุไหงปาดี',
}

def init_gis():
    global _GIS_TREE, _GIS_GEOMS, _GIS_PROPS, _GIS_CENTROIDS, _GIS_TAM_PROV, _GIS_AMP_PROV
    global _GIS_DIST_CENTROIDS, _GIS_ALL_PROVINCES, _GIS_SORTED_PROVINCES, _GIS_AMP_TO_PROV, _GIS_TAM_TO_AMP_PROV, _GIS_GEOM_MAP, _GIS_INIT_TRIED
    if _GIS_TREE is not None or _GIS_INIT_TRIED:
        return
    with _GIS_LOCK:
        if _GIS_TREE is not None or _GIS_INIT_TRIED:
            return
        _GIS_INIT_TRIED = True
        try:
            import os, sys, json
            from shapely.geometry import shape
            from shapely.strtree import STRtree
            
            candidates = []
            if getattr(sys, '_MEIPASS', None):
                candidates.append(os.path.join(sys._MEIPASS, "subdistricts.geojson"))
            base_dir = os.path.dirname(os.path.abspath(__file__))
            candidates.append(os.path.join(base_dir, "subdistricts.geojson"))
            candidates.append(os.path.join(os.path.dirname(base_dir), "subdistricts.geojson"))
            candidates.append(os.path.join(os.path.dirname(base_dir), "data", "subdistricts.geojson"))
            
            geojson_path = next((p for p in candidates if os.path.exists(p)), None)
            if geojson_path:
                with open(geojson_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                geoms = []
                props = []
                centroids = {}
                tam_prov = {}
                amp_prov = {}
                amp_coords_accum = {}
                dist_centroids = set()
                all_provinces = set()
                amp_to_prov = {}
                tam_to_amp_prov = {}
                geom_map = {}
                
                for feat in data.get("features", []):
                    geom = shape(feat["geometry"])
                    geoms.append(geom)
                    p = feat.get("properties", {})
                    tam = p.get("tam_th", "").strip()
                    amp = p.get("amp_th", "").strip()
                    pro = p.get("pro_th", "").strip()
                    if tam in SPECIAL_TAM_CLEAN:
                        tam = SPECIAL_TAM_CLEAN[tam]
                    if "กรุงเทพ" in pro:
                        pro = "กรุงเทพมหานคร"
                        
                    prop_tuple = (tam, amp, pro)
                    props.append(prop_tuple)
                    geom_map[id(geom)] = prop_tuple
                    
                    c = geom.centroid
                    coords = (round(c.y, 6), round(c.x, 6))
                    centroids[(tam, amp, pro)] = coords
                    tam_prov[(tam, pro)] = coords
                    amp_coords_accum.setdefault((amp, pro), []).append(coords)
                    
                    all_provinces.add(pro)
                    if amp not in amp_to_prov: amp_to_prov[amp] = set()
                    amp_to_prov[amp].add(pro)
                    
                    if tam not in tam_to_amp_prov: tam_to_amp_prov[tam] = []
                    if (amp, pro) not in tam_to_amp_prov[tam]:
                        tam_to_amp_prov[tam].append((amp, pro))

                # Compute mean subdistrict centroids per (amp, pro) as default
                for k_ap, clist in amp_coords_accum.items():
                    mean_c = (
                        round(sum(pt[0] for pt in clist) / len(clist), 6),
                        round(sum(pt[1] for pt in clist) / len(clist), 6)
                    )
                    amp_prov[k_ap] = mean_c
                    dist_centroids.add(mean_c)

                # Load true district centroids from districts.geojson if available
                dist_candidates = []
                if getattr(sys, '_MEIPASS', None):
                    dist_candidates.append(os.path.join(sys._MEIPASS, "districts.geojson"))
                dist_candidates.extend([
                    os.path.join(base_dir, "districts.geojson"),
                    os.path.join(os.path.dirname(base_dir), "districts.geojson"),
                    os.path.join(os.path.dirname(base_dir), "data", "districts.geojson"),
                ])
                dist_geojson_path = next((dp for dp in dist_candidates if os.path.exists(dp)), None)
                if dist_geojson_path:
                    try:
                        with open(dist_geojson_path, "r", encoding="utf-8") as df_in:
                            ddata = json.load(df_in)
                        for feat in ddata.get("features", []):
                            d_geom = shape(feat["geometry"])
                            dc = d_geom.centroid
                            d_coords = (round(dc.y, 6), round(dc.x, 6))
                            dist_centroids.add(d_coords)
                            dp_props = feat.get("properties", {})
                            d_amp = str(dp_props.get("amp_th") or "").strip()
                            d_pro = str(dp_props.get("pro_th") or "").strip()
                            if "กรุงเทพ" in d_pro:
                                d_pro = "กรุงเทพมหานคร"
                            if d_amp and d_pro:
                                amp_prov[(d_amp, d_pro)] = d_coords
                    except Exception:
                        pass

                _GIS_GEOMS = geoms
                _GIS_PROPS = props
                _GIS_CENTROIDS = centroids
                _GIS_TAM_PROV = tam_prov
                _GIS_AMP_PROV = amp_prov
                _GIS_DIST_CENTROIDS = dist_centroids
                _GIS_ALL_PROVINCES = all_provinces
                _GIS_SORTED_PROVINCES = sorted(all_provinces, key=len, reverse=True)
                _GIS_AMP_TO_PROV = amp_to_prov
                _GIS_TAM_TO_AMP_PROV = tam_to_amp_prov
                _GIS_GEOM_MAP = geom_map
                _GIS_TREE = STRtree(geoms)
        except Exception:
            pass

def get_known_centroids_set():
    """Return a set of string keys 'lat,lon' rounded to 5 decimal places for all known GIS centroids."""
    init_gis()
    all_known = (
        set(_GIS_CENTROIDS.values())
        .union(_GIS_TAM_PROV.values())
        .union(_GIS_AMP_PROV.values())
        .union(_GIS_DIST_CENTROIDS or set())
    ) if _GIS_CENTROIDS else set()
    return {f"{round(lt, 5)},{round(ln, 5)}" for lt, ln in all_known}

_GIS_CENTROIDS_GRID = None

def _get_centroids_grid():
    global _GIS_CENTROIDS_GRID
    if _GIS_CENTROIDS_GRID is not None:
        return _GIS_CENTROIDS_GRID
    with _GIS_LOCK:
        if _GIS_CENTROIDS_GRID is not None:
            return _GIS_CENTROIDS_GRID
        init_gis()
        all_raw = (
            list(_GIS_CENTROIDS.values())
            + list(_GIS_TAM_PROV.values())
            + list(_GIS_AMP_PROV.values())
            + list(_GIS_DIST_CENTROIDS or [])
        ) if _GIS_CENTROIDS else []
        grid = {}
        for clat, clon in set(all_raw):
            gx = int(round(clat * 1000))
            gy = int(round(clon * 1000))
            grid.setdefault((gx, gy), []).append((clat, clon))
        _GIS_CENTROIDS_GRID = grid
        return grid

def is_centroid_coord(lat, lon, centroids_set=None, tol=0.00005):
    """Check if a coordinate pair (lat, lon) matches an administrative centroid within distance tolerance."""
    if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
        return False
    try:
        s_lat = str(lat).replace(',', '').strip()
        s_lon = str(lon).replace(',', '').strip()
        if not s_lat or not s_lon:
            return False
        lt = float(s_lat)
        ln = float(s_lon)
    except (ValueError, TypeError):
        return False
    grid = _get_centroids_grid()
    gx = int(round(lt * 1000))
    gy = int(round(ln * 1000))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for clat, clon in grid.get((gx + dx, gy + dy), []):
                if abs(clat - lt) <= tol and abs(clon - ln) <= tol:
                    return True
    return False

def forward_geocode_location(tam, amp, prov):
    """
    Given (ตำบล, อำเภอ, จังหวัด), returns (latitude, longitude) centroid from GIS boundaries.
    """
    init_gis()
    if not _GIS_CENTROIDS:
        return None, None
    
    t = clean_location_field(tam, is_amphoe=False)
    a = clean_location_field(amp, is_amphoe=True)
    p = str(prov or '').strip()
    p = re.sub(r'^(?:จังหวัด)\s*', '', p).strip()
    if "กรุงเทพ" in p:
        p = "กรุงเทพมหานคร"
        
    # 1. Exact match
    if (t, a, p) in _GIS_CENTROIDS:
        return _GIS_CENTROIDS[(t, a, p)]
        
    # 2. Try 'เมือง' + p for Amphoe
    if a in ['เมือง', 'อำเภอเมือง', 'เมือง' + p]:
        a_m = 'เมือง' + p
        if (t, a_m, p) in _GIS_CENTROIDS:
            return _GIS_CENTROIDS[(t, a_m, p)]
            
    # 3. Fallback (tam, pro)
    if (t, p) in _GIS_TAM_PROV:
        return _GIS_TAM_PROV[(t, p)]
        
    # 4. Fallback (amp, pro)
    if (a, p) in _GIS_AMP_PROV:
        return _GIS_AMP_PROV[(a, p)]
        
    return None, None

def reverse_geocode_location(lat, lng):
    if lat is None or lng is None or pd.isna(lat) or pd.isna(lng):
        return "", "", ""
    if not lat or not lng or str(lat).strip().lower() in ["nan", "none", "<na>", ""]:
        return "", "", ""
    try:
        lat_f = float(lat)
        lng_f = float(lng)
        if not (5.0 <= lat_f <= 21.0 and 97.0 <= lng_f <= 106.0):
            return "", "", ""
        init_gis()
        if _GIS_TREE is not None and _GIS_PROPS is not None:
            from shapely.geometry import Point
            import numpy as np
            pt = Point(lng_f, lat_f)
            
            # Method 1: Shapely 2.0 query with predicate
            try:
                res = _GIS_TREE.query(pt, predicate='intersects')
                if len(res) > 0:
                    first = res[0]
                    if isinstance(first, (int, np.integer)):
                        for idx in res:
                            if _GIS_GEOMS[int(idx)].contains(pt):
                                return _GIS_PROPS[int(idx)]
                        return _GIS_PROPS[int(first)]
                    elif hasattr(first, 'contains'):
                        for cand in res:
                            if cand.contains(pt):
                                return _GIS_GEOM_MAP.get(id(cand), ("", "", ""))
                        return _GIS_GEOM_MAP.get(id(first), ("", "", ""))
            except Exception:
                pass
                
            # Method 2: Standard query fallback (compatible with Shapely 1.8 & 2.0)
            try:
                res = _GIS_TREE.query(pt)
                if len(res) > 0:
                    first = res[0]
                    if isinstance(first, (int, np.integer)):
                        for idx in res:
                            g = _GIS_GEOMS[int(idx)]
                            if g.contains(pt):
                                return _GIS_PROPS[int(idx)]
                        for idx in res:
                            g = _GIS_GEOMS[int(idx)]
                            if g.intersects(pt) or g.touches(pt):
                                return _GIS_PROPS[int(idx)]
                        best_idx = min(res, key=lambda idx: _GIS_GEOMS[int(idx)].distance(pt))
                        if _GIS_GEOMS[int(best_idx)].distance(pt) < 0.01:
                            return _GIS_PROPS[int(best_idx)]
                    else:
                        for cand in res:
                            if cand.contains(pt):
                                return _GIS_GEOM_MAP.get(id(cand), ("", "", ""))
                        for cand in res:
                            if cand.intersects(pt) or cand.touches(pt):
                                return _GIS_GEOM_MAP.get(id(cand), ("", "", ""))
                        best_cand = min(res, key=lambda c: c.distance(pt))
                        if best_cand.distance(pt) < 0.01:
                            return _GIS_GEOM_MAP.get(id(best_cand), ("", "", ""))
            except Exception:
                pass
                
            # Method 3: Nearest query
            try:
                nearest = _GIS_TREE.query_nearest(pt)
                if len(nearest) > 0:
                    first = nearest[0]
                    if isinstance(first, (list, tuple, np.ndarray)):
                        first = first[0]
                    if isinstance(first, (int, np.integer)):
                        return _GIS_PROPS[int(first)]
                    else:
                        return _GIS_GEOM_MAP.get(id(first), ("", "", ""))
            except Exception:
                pass
                
        # Method 4: Centroid nearest fallback (Fail-safe for border points)
        if _GIS_CENTROIDS:
            best_match = None
            min_dist_sq = float('inf')
            for (tam_c, amp_c, pro_c), (c_lat, c_lng) in _GIS_CENTROIDS.items():
                d_sq = (lat_f - c_lat)**2 + (lng_f - c_lng)**2
                if d_sq < min_dist_sq:
                    min_dist_sq = d_sq
                    best_match = (tam_c, amp_c, pro_c)
            if best_match and min_dist_sq < 0.08:  # within ~30 km
                return best_match
    except Exception:
        pass
    return "", "", ""

def _resolve_text_locations(t_raw, a_raw, p_raw):
    """
    Intelligently resolves and normalizes (ตำบล, อำเภอ, จังหวัด) without coordinates:
    - Resolves 'เมือง' -> 'เมือง{จังหวัด}'
    - Detects subdistricts misplaced as districts (e.g. ลุมพินี, สีลม -> district ปทุมวัน, บางรัก)
    - Maps common marketing zones (พัทยา, บางแสน, เขาใหญ่, อโศก, อ่อนนุช, ฯลฯ)
    - Removes junk text (ห้องนอน, ห้องน้ำ, ไร่, ซอย, ถนน)
    """
    init_gis()
    
    # 1. Clean Province
    p = str(p_raw or '').strip()
    p = re.sub(r'[\(\[\{].*$', '', p).strip()
    p = re.sub(r'^(?:จ\.|จังหวัด)\s*', '', p).strip()
    if p in ["อยุธยา", "จ.อยุธยา", "กรุงเก่า"]:
        p = "พระนครศรีอยุธยา"
    elif p == "สุราษฏร์ธานี":
        p = "สุราษฎร์ธานี"
    elif "กรุงเทพ" in p or "กทม" in p:
        p = "กรุงเทพมหานคร"
    if p.lower() in ["อื่นๆ", "-", "", "nan", "none", "null", "undefined", "<na>"]:
        p = ""
    # Enforce strictly valid Thai province (no numeric years/junk, must start with Thai letter)
    if p:
        if re.search(r'\d', p) or not re.search(r'^[ก-๙]', p):
            p = ""
        elif _GIS_ALL_PROVINCES and p not in _GIS_ALL_PROVINCES:
            p_alt = p.replace('ฏ', 'ฎ')
            if p_alt in _GIS_ALL_PROVINCES:
                p = p_alt
            else:
                is_known_amp_or_tam = bool(
                    (_GIS_AMP_TO_PROV and p in _GIS_AMP_TO_PROV)
                    or (_GIS_TAM_TO_AMP_PROV and p in _GIS_TAM_TO_AMP_PROV)
                )
                matched_prov = ""
                if not is_known_amp_or_tam:
                    sorted_provs = _GIS_SORTED_PROVINCES or sorted(_GIS_ALL_PROVINCES, key=len, reverse=True)
                    for gp in sorted_provs:
                        if gp == "ตาก" and "ตากใบ" in p:
                            continue
                        if gp in p or gp in p_alt:
                            matched_prov = gp
                            break
                    if not matched_prov and len(p) >= 4:
                        for gp in sorted_provs:
                            if p in gp or p_alt in gp:
                                matched_prov = gp
                                break
                p = matched_prov

    # 2. Check Popular Zone Mapping on District and Subdistrict
    a_raw_s = str(a_raw or '').strip() if not pd.isna(a_raw) else ''
    if re.search(r'[\(\[\{][^)\]\}]*[a-zA-Z]', a_raw_s):
        a = a_raw_s
    else:
        a = re.sub(r'[\(\[\{].*$', '', a_raw_s).strip()
    t = re.sub(r'[\(\[\{].*$', '', str(t_raw or '') if not pd.isna(t_raw) else '').strip()
    if a.lower() in ["nan", "none", "null", "undefined", "<na>", "-"]: a = ""
    if t.lower() in ["nan", "none", "null", "undefined", "<na>", "-"]: t = ""
    
    a_zone = re.sub(r'[\(\[\{].*$', '', a).strip()
    t_cand = clean_location_field(t, is_amphoe=False) if t else ""
    a_cand = clean_location_field(a_zone, is_amphoe=True) if a_zone else ""
    is_official_amp_of_p = bool(
        _GIS_AMP_TO_PROV and a_cand in _GIS_AMP_TO_PROV and (not p or p in _GIS_AMP_TO_PROV[a_cand])
    )
    if a_zone in POPULAR_ZONE_MAPPING:
        zone = POPULAR_ZONE_MAPPING[a_zone]
        # Skip marketing-zone override if province explicitly disagrees or if it's already an official district+subdistrict in another province
        same_or_empty_prov = (not p) or (p == zone['จังหวัด'])
        has_real_subdist_in_a = bool(
            _GIS_CENTROIDS and p and t_cand and a_cand and (t_cand, a_cand, p) in _GIS_CENTROIDS
        )
        if same_or_empty_prov and not has_real_subdist_in_a and not (is_official_amp_of_p and p and p != zone['จังหวัด']):
            if not t or t == a_zone:
                t = zone['ตำบล']
            a = zone['อำเภอ']
            if not p:
                p = zone['จังหวัด']
        
    if t in POPULAR_ZONE_MAPPING:
        zone = POPULAR_ZONE_MAPPING[t]
        same_or_empty_prov = (not p) or (p == zone['จังหวัด'])
        # Only expand subdistrict marketing alias when it is NOT already a real subdistrict for that province
        is_official_tam_of_p = bool(
            _GIS_TAM_PROV and p and t_cand and (t_cand, p) in _GIS_TAM_PROV
        )
        is_official_tam_with_a = bool(
            _GIS_CENTROIDS and p and t_cand and a_cand and (t_cand, a_cand, p) in _GIS_CENTROIDS
        )
        if same_or_empty_prov and not is_official_tam_of_p and not is_official_tam_with_a and not (a_zone and _GIS_AMP_TO_PROV and a_cand in _GIS_AMP_TO_PROV and p and p in _GIS_AMP_TO_PROV[a_cand]):
            t = zone['ตำบล']
            if not a_zone:
                a = zone['อำเภอ']
            if not p:
                p = zone['จังหวัด']

    clean_t = clean_location_field(t, is_amphoe=False)
    clean_a = clean_location_field(a, is_amphoe=True)

    # 3. Fix Truncated Amphoe names from Government sources
    if clean_a in TRUNCATED_AMPHOE_FIX:
        clean_a = TRUNCATED_AMPHOE_FIX[clean_a]

    # 4. Clean 'เมือง' / 'อำเภอเมือง' -> 'เมือง{จังหวัด}'
    if clean_a in ['เมือง', 'อำเภอเมือง'] and p:
        a_m = f"เมือง{p}"
        if _GIS_AMP_TO_PROV and a_m in _GIS_AMP_TO_PROV:
            clean_a = a_m

    # 5. Fix 'บางนา-ตราด' bug (where 'ตราด' matched as province)
    if p == "ตราด" and ("บางนา" in clean_a or "บางนา" in clean_t):
        p = "สมุทรปราการ"
        clean_a = "บางพลี"
        if not clean_t or clean_t == "บางนา": clean_t = "บางแก้ว"
    elif p == "สมุทรปราการ" and clean_a == "บางนา":
        p = "กรุงเทพมหานคร"

    # 6. Fix cross-province parsing anomalies
    if clean_a == "กันทรลักษ์":
        p = "ศรีสะเกษ"
    elif p == "กรุงเทพมหานคร":
        if clean_a == "ศรีราชา": p = "ชลบุรี"
        elif clean_a == "ปากช่อง": p = "นครราชสีมา"
        elif clean_a == "ส่องดาว": p = "สกลนคร"
        elif clean_a in ["ปากเกร็ด", "เมืองนนทบุรี"]: p = "นนทบุรี"
    elif p == "นราธิวาส" and clean_a == "สาทร":
        p = "กรุงเทพมหานคร"

    # 7. Standardize subdistrict names according to official master
    if clean_a == "บางละมุง" and clean_t in ["เมืองพัทยา", "พัทยา"]:
        clean_t = "หนองปรือ"
    elif p == "กรุงเทพมหานคร" and clean_a == "บางนา" and clean_t in ["บางนา", ""]:
        clean_t = "บางนาเหนือ"
    elif p == "กรุงเทพมหานคร" and clean_a == "บางบอน" and clean_t in ["บางบอน", ""]:
        clean_t = "บางบอนเหนือ"
    elif clean_t in ["ศรีษะจรเข้น้อย", "ศีรษะจรเข้น้อย"]:
        clean_t = "ศีรษะจรเข้น้อย"
    elif clean_t in ["ศรีษะจรเข้ใหญ่", "ศีรษะจรเข้ใหญ่"]:
        clean_t = "ศีรษะจรเข้ใหญ่"
    elif clean_t == "ดอนหัวฬอ":
        clean_t = "ดอนหัวฬ่อ"

    # 8. Misplaced Subdistrict in Amphoe column or infer district from clean_t
    is_valid_amp_of_p = bool(_GIS_AMP_TO_PROV and clean_a in _GIS_AMP_TO_PROV and (not p or p in _GIS_AMP_TO_PROV[clean_a]))
    if not is_valid_amp_of_p and clean_a and _GIS_TAM_TO_AMP_PROV and clean_a in _GIS_TAM_TO_AMP_PROV:
        matches = _GIS_TAM_TO_AMP_PROV[clean_a]
        chosen = None
        if p:
            p_matches = [m for m in matches if m[1] == p]
            if p_matches: chosen = p_matches[0]
        if not chosen and matches:
            chosen = matches[0]
            
        if chosen:
            real_amp, real_prov = chosen
            if not clean_t or clean_t == clean_a or clean_t == p:
                clean_t = clean_a
            clean_a = real_amp
            if not p:
                p = real_prov
    elif not clean_a and clean_t and _GIS_TAM_TO_AMP_PROV and clean_t in _GIS_TAM_TO_AMP_PROV:
        matches = _GIS_TAM_TO_AMP_PROV[clean_t]
        if p:
            p_matches = [m for m in matches if m[1] == p]
            if p_matches: matches = p_matches
        if matches:
            clean_a, real_prov = matches[0]
            if not p:
                p = real_prov

    # 9. Clean Province typed into Subdistrict ONLY if it is NOT an actual official subdistrict in that province (e.g. ต.ชัยนาท จ.ชัยนาท)
    if clean_t and clean_t == p:
        is_valid_self_tam = bool(
            (_GIS_CENTROIDS and clean_a and (clean_t, clean_a, p) in _GIS_CENTROIDS)
            or (_GIS_TAM_PROV and (clean_t, p) in _GIS_TAM_PROV)
        )
        if not is_valid_self_tam:
            clean_t = ""

    # 10. Infer province from unique district if province is missing
    if not p and clean_a and _GIS_AMP_TO_PROV and clean_a in _GIS_AMP_TO_PROV:
        provs = list(_GIS_AMP_TO_PROV[clean_a])
        if len(provs) == 1:
            p = provs[0]

    # 11. Absolute guarantee: NO English characters allowed in clean_a or clean_t
    if re.search(r'[a-zA-Z]', clean_a):
        clean_a = translate_amphoe_en_to_th(clean_a)
        if not re.match(r'^[ก-๙]', clean_a):
            clean_a = ""

    if re.search(r'[a-zA-Z]', clean_t):
        clean_t = re.sub(r'[a-zA-Z]', '', clean_t).strip()
        if not re.match(r'^[ก-๙]', clean_t):
            clean_t = ""

    if str(clean_t).strip().lower() in ["nan", "none", "null", "undefined", "-", "อื่นๆ"]:
        clean_t = ""
    if str(clean_a).strip().lower() in ["nan", "none", "null", "undefined", "-", "อื่นๆ"]:
        clean_a = ""
    if str(p).strip().lower() in ["nan", "none", "null", "undefined", "-", "อื่นๆ"]:
        p = ""

    return clean_t, clean_a, p

def clean_row_location(tam, amp=None, prov=None, lat=None, lng=None, impute_coords=True):
    """
    Cleans a complete location row (ตำบล, อำเภอ, จังหวัด):
    Supports two calling signatures:
    1. Dictionary mode: clean_row_location(row_dict, impute_coords=True) -> modifies & returns row_dict
    2. Positional mode: clean_row_location(tam, amp, prov, lat, lng) -> returns (clean_t, clean_a, clean_p)
    """
    if isinstance(tam, dict):
        row = tam
        t = row.get("ตำบล", "")
        a = row.get("อำเภอ", "")
        p = row.get("จังหวัด", "")
        la = row.get("ละติจูด")
        lo = row.get("ลองจิจูด")
        comp_upper = str(row.get("บริษัท", "")).strip().upper()

        # Pre-validate coordinates: clear 0/0.0, out-of-bounds, or centroid coordinates for LED Legal (LED_SOLD)
        has_valid_coords = False
        lat_f = None
        lng_f = None
        if la is not None and lo is not None and not pd.isna(la) and not pd.isna(lo) and str(la).strip().lower() not in ["nan", "none", "null", "undefined", "<na>", "", "0", "0.0"] and str(lo).strip().lower() not in ["nan", "none", "null", "undefined", "<na>", "", "0", "0.0"]:
            try:
                lat_f = float(str(la).replace(',', '').strip())
                lng_f = float(str(lo).replace(',', '').strip())
                if 5.0 <= lat_f <= 21.0 and 97.0 <= lng_f <= 106.0:
                    if comp_upper in ("LED LEGAL", "LED_LEGAL", "LED_SOLD") and is_centroid_coord(lat_f, lng_f):
                        row["ละติจูด"] = ""
                        row["ลองจิจูด"] = ""
                        la = ""
                        lo = ""
                    else:
                        has_valid_coords = True
                else:
                    row["ละติจูด"] = ""
                    row["ลองจิจูด"] = ""
                    la = ""
                    lo = ""
            except Exception:
                row["ละติจูด"] = ""
                row["ลองจิจูด"] = ""
                la = ""
                lo = ""
        else:
            row["ละติจูด"] = ""
            row["ลองจิจูด"] = ""
            la = ""
            lo = ""
        
        # 1. If valid lat/lng exists, use 100% verified Reverse-Geocode from offline GIS
        if has_valid_coords and lat_f is not None and lng_f is not None:
            try:
                sd_gis, d_gis, p_gis = reverse_geocode_location(lat_f, lng_f)
                if p_gis:
                    clean_sd_gis = "" if str(sd_gis).strip().lower() in ["nan", "none", "null", "undefined", "-"] else str(sd_gis).strip()
                    clean_d_gis = "" if str(d_gis).strip().lower() in ["nan", "none", "null", "undefined", "-"] else str(d_gis).strip()
                    if clean_sd_gis:
                        row["ตำบล"] = clean_sd_gis
                    elif row.get("ตำบล"):
                        row["ตำบล"] = clean_location_field(row.get("ตำบล"))
                    if clean_d_gis:
                        row["อำเภอ"] = clean_d_gis
                    elif row.get("อำเภอ"):
                        row["อำเภอ"] = clean_location_field(row.get("อำเภอ"), is_amphoe=True)
                    row["จังหวัด"] = str(p_gis).strip()
                    return row
            except Exception:
                pass
                
        # 2. Text resolution & Administrative normalization
        clean_t, clean_a, clean_p = _resolve_text_locations(t, a, p)
        row["ตำบล"] = clean_t
        row["อำเภอ"] = clean_a
        row["จังหวัด"] = clean_p
        
        # 3. Forward geocode Centroid to restore missing coordinates (never impute for LED Legal / LED_SOLD)
        should_impute = impute_coords and not row.get("skip_centroid", False) and comp_upper not in ("LED LEGAL", "LED_LEGAL", "LED_SOLD")
        if should_impute and not has_valid_coords and (clean_t or clean_a) and clean_p:
            c_lat, c_lng = forward_geocode_location(clean_t, clean_a, clean_p)
            if c_lat and c_lng:
                row["ละติจูด"] = c_lat
                row["ลองจิจูด"] = c_lng
        elif not has_valid_coords:
            row["ละติจูด"] = ""
            row["ลองจิจูด"] = ""

        # Strictly clear centroid coordinates if this is LED Legal / LED_SOLD
        if comp_upper in ("LED LEGAL", "LED_LEGAL", "LED_SOLD") and is_centroid_coord(row.get("ละติจูด"), row.get("ลองจิจูด")):
            row["ละติจูด"] = ""
            row["ลองจิจูด"] = ""
                
        for k in ["ตำบล", "อำเภอ", "จังหวัด"]:
            val_k = str(row.get(k) or "").strip()
            if val_k.lower() in ["nan", "none", "null", "undefined", "-", "อื่นๆ"]:
                row[k] = ""
            else:
                row[k] = val_k
        if row.get("จังหวัด"):
            pv = str(row.get("จังหวัด", "")).strip()
            if re.search(r'\d', pv) or not re.search(r'^[ก-๙]', pv) or (_GIS_ALL_PROVINCES and pv not in _GIS_ALL_PROVINCES):
                row["จังหวัด"] = ""

        # Absolute guarantee: no English characters in 'อำเภอ'
        if re.search(r'[a-zA-Z]', str(row.get("อำเภอ", ""))):
            row["อำเภอ"] = translate_amphoe_en_to_th(str(row.get("อำเภอ", "")))
            if not re.match(r'^[ก-๙]', str(row.get("อำเภอ", ""))):
                row["อำเภอ"] = ""

        return row

    # Positional mode
    if lat is not None and lng is not None and not pd.isna(lat) and not pd.isna(lng) and str(lat).strip().lower() not in ["nan", "none", "<na>", ""] and str(lng).strip().lower() not in ["nan", "none", "<na>", ""]:
        try:
            lat_f = float(lat)
            lng_f = float(lng)
            if 5.0 <= lat_f <= 21.0 and 97.0 <= lng_f <= 106.0:
                sd_gis, d_gis, p_gis = reverse_geocode_location(lat_f, lng_f)
                if p_gis:
                    return (
                        "" if str(sd_gis).strip().lower() in ["nan", "none", "null", "undefined", "-"] else str(sd_gis).strip(),
                        "" if str(d_gis).strip().lower() in ["nan", "none", "null", "undefined", "-"] else str(d_gis).strip(),
                        "" if str(p_gis).strip().lower() in ["nan", "none", "null", "undefined", "-"] else str(p_gis).strip()
                    )
        except Exception:
            pass
            
    clean_t, clean_a, clean_p = _resolve_text_locations(tam, amp, prov)
    
    # Absolute guarantee: no English characters in clean_a
    if re.search(r'[a-zA-Z]', str(clean_a)):
        clean_a = translate_amphoe_en_to_th(clean_a)
        if not re.match(r'^[ก-๙]', str(clean_a)):
            clean_a = ""

    return (
        "" if str(clean_t).strip().lower() in ["nan", "none", "null", "undefined", "-"] else str(clean_t).strip(),
        "" if str(clean_a).strip().lower() in ["nan", "none", "null", "undefined", "-"] else str(clean_a).strip(),
        "" if str(clean_p).strip().lower() in ["nan", "none", "null", "undefined", "-"] else str(clean_p).strip()
    )

def clean_price_val(val):
    """
    Cleans property price values:
    - If price is lower than 500 Baht (or 0, negative, invalid) -> returns None
    - If price was glued/concatenated range (e.g. 1890000021900000) -> splits and restores starting price
    - If price is valid (>= 500 Baht) -> returns cleaned float
    """
    if val is None or pd.isna(val):
        return None
    s = str(val).strip().replace(",", "")
    if not s or s.lower() in ["nan", "none", "null", "-", "0", "0.0", "0.00"]:
        return None
    try:
        p_val = float(s)
        if p_val < 500.0:
            return None
        # Handle glued range numbers (e.g. 1890000021900000 -> 18,900,000)
        if p_val > 1e11:
            digits = re.sub(r'[^\d]', '', s.split('.')[0])
            if len(digits) in (14, 15, 16):
                half = len(digits) // 2
                first_p = float(digits[:half])
                if 10_000 <= first_p <= 1e9:
                    return first_p
            elif len(digits) == 13:
                first_p = float(digits[:6])
                if 10_000 <= first_p <= 1e9:
                    return first_p
        return p_val
    except (ValueError, TypeError):
        return None

def clean_floor_val(val, usable_area=None):
    """
    ทำความสะอาดและจัดรูปแบบค่าชั้นของทรัพย์สิน
    - หากเป็นตัวเลข เช่น 5, '8' -> '5', '8'
    - หากเป็นรูปแบบ 'ชั้น 12' -> '12'
    - หากเป็นจำนวนชั้นของอาคาร เช่น '2 ชั้น', '3.5 ชั้น' -> '2 ชั้น'
    - กรองค่าว่าง, nan, none -> None
    - กรองและปฏิเสธข้อความที่เป็นพื้นที่ เช่น 'พื้นที่ชั้น 50 ตร.ม.', 'พื้นที่ใช้สอย', หน่วย ตร.ม., ตารางเมตร
    - กรองตัวเลขชั้นที่ไม่สมเหตุสมผล (เช่น >= 80 หรือค่าที่ตรงกับขนาดพื้นที่ใช้สอย)
    """
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    if not s or s.lower() in ["nan", "none", "null", "-", "0", "0.0"]:
        return None

    # หากมีค่าพื้นที่ใช้สอยมาเปรียบเทียบ และค่าชั้นตรงกับพื้นที่ใช้สอย (>= 8) แสดงว่าดึงพื้นที่มาผิด
    if usable_area is not None and not pd.isna(usable_area):
        try:
            u_clean = float(re.sub(r'[^\d\.]', '', str(usable_area)))
            f_clean = float(re.sub(r'[^\d\.]', '', s))
            if u_clean > 8 and abs(f_clean - u_clean) < 1.0:
                return None
        except (ValueError, TypeError):
            pass

    # ปฏิเสธค่าที่เป็นพื้นที่/ขนาดพื้นที่/ราคาต่อตารางเมตรอย่างชัดเจน
    if re.search(r'พื้นที่|ตร\.?ม|ตรม|ตารางเมตร|sqm|sq\.?m|ตร\.?ว|ตารางวา|sqft', s, re.I):
        m_explicit = re.search(r'(?<!พื้นที่)ชั้น(?:ที่)?\s*[:\s]*([0-9]{1,2}[A-Za-z]?|G|M|B[1-9]?|ลอย)\b(?!\s*(?:ตร\.?ม|ตรม|ตารางเมตร|sqm|sq\.?m|วา|ตร\.?ว|ตารางวา))', s, re.I)
        if m_explicit:
            val_u = m_explicit.group(1).strip()
            if not (val_u.isdigit() and int(val_u) >= 80):
                return val_u
        m_story_explicit = re.search(r'(?<![\d/])([1-9](?:\.[0-9]+)?)\s*ชั้น(?!\s*(?:ที่|ตร\.?ม|ตรม|ตารางเมตร))', s)
        if m_story_explicit:
            return f"{m_story_explicit.group(1).strip()} ชั้น"
        return None

    # If pure number
    if re.match(r'^\d+$', s):
        n = int(s)
        if n >= 80 or n <= 0:
            return None
        return str(n)

    # If float ending with .0 e.g. 5.0
    if re.match(r'^\d+\.0+$', s):
        n = int(float(s))
        if n >= 80 or n <= 0:
            return None
        return str(n)

    # Match 'ชั้น 12' or 'ชั้นที่ 12' or 'ชั้นที่ : 12' (ต้องไม่ตามหลังคำว่า 'พื้นที่')
    m = re.search(r'(?<!พื้นที่)ชั้น(?:ที่)?\s*[:\s]*([0-9]{1,2}[A-Za-z]?|G|M|B[1-9]?|ลอย)\b(?!\s*(?:ตร\.?ม|ตรม|ตารางเมตร|sqm|sq\.?m|วา|ตร\.?ว|ตารางวา))', s, re.I)
    if m:
        val_u = m.group(1).strip()
        if val_u.isdigit() and int(val_u) >= 80:
            return None
        return val_u

    # Match '2 ชั้น' or '3 ชั้น'
    m2 = re.search(r'(?<![\d/])([1-9][0-9]?(?:\.[0-9]+)?)\s*ชั้น(?!\s*(?:ที่|ตร\.?ม|ตรม|ตารางเมตร))', s)
    if m2:
        story_val = float(m2.group(1).strip())
        if story_val >= 80:
            return None
        return f"{m2.group(1).strip()} ชั้น"

    # จัดการกรณีคำระบุชั้นพิเศษ เช่น 'ชั้นล่าง', 'ชั้นบน', 'ใต้ดิน'
    m_special = re.search(r'ชั้น(?:ที่)?\s*[:\s]*(ใต้ดิน|ดาดฟ้า|ลอย|ล่าง|บน)', s)
    if m_special:
        return m_special.group(1).strip()

    return None

def extract_floor_from_text(*texts, asset_type=""):
    """
    สกัดข้อมูลชั้นหรือจำนวนชั้นจากข้อความ (ชื่อประกาศ, รายละเอียด, หมายเหตุ)
    - คอนโด/ห้องชุด: สกัดชั้นของยูนิต เช่น '12', '12A', 'G'
    - บ้าน/ตึกแถว/อาคารพาณิชย์: สกัดจำนวนชั้น เช่น '2 ชั้น', '3.5 ชั้น'
    - ป้องกันการดึงตัวเลขหลังคำว่า 'พื้นที่ชั้น' หรือ 'พื้นที่ใช้สอย' หรือหน่วย ตร.ม. มาเป็นชั้น
    """
    combined = " ".join(str(t) for t in texts if t and str(t).lower() not in ["nan", "none"]).strip()
    if not combined:
        return None
        
    is_land = any(k in str(asset_type) for k in ["ที่ดิน", "ที่ดินเปล่า", "land"])
    if is_land:
        return None
        
    is_condo = any(k in str(asset_type) for k in ["คอนโด", "ห้องชุด", "อาคารชุด", "condo", "apartment", "อพาร์ทเม้นท์"])
    
    # ทำความสะอาดข้อความ ลบคำที่เกี่ยวกับพื้นที่ชั้นและพื้นที่ใช้สอยออกก่อน เพื่อไม่ให้รบกวนการสกัดชั้น
    cleaned = re.sub(r'฿?[\d\.,\s\w\/\(\)]*ตารางเมตร\s*\([^\)]*พื้นที่ชั้น[^\)]*\)', ' ', combined, flags=re.I)
    cleaned = re.sub(r'พื้นที่(?:ชั้น|ใช้สอย|ห้อง|ดิน)?\s*[:\s]*[\d\.,]+\s*(?:ตร\.?ม|ตรม|ตารางเมตร|ตร\.?ว|ตร\.วา|ตารางวา|sqm|sq\.?m|sqft)?', ' ', cleaned, flags=re.I)
    cleaned = re.sub(r'[\d\.,]+\s*(?:ตร\.?ม|ตรม|ตารางเมตร|ตร\.?ว|ตร\.วา|ตารางวา|sqm|sq\.?m|sqft)\s*\([^\)]*พื้นที่(?:ชั้น|ใช้สอย)?[^\)]*\)', ' ', cleaned, flags=re.I)

    # สำหรับบ้าน ทาวน์โฮม อาคารพาณิชย์ ตึกแถว: สกัดจำนวนชั้นเท่านั้น (1-10 ชั้น)
    if not is_condo:
        m_story = re.search(r'(?<![\d/])([1-9](?:\.[0-9]+)?)\s*ชั้น(?!\s*(?:ที่|ตร\.?ม|ตรม|ตารางเมตร))', cleaned)
        if m_story and float(m_story.group(1)) <= 10:
            return f"{m_story.group(1).strip()} ชั้น"
        return None

    # สำหรับคอนโด/ห้องชุด:
    # 1. ค้นหาชั้นของยูนิต เช่น 'ชั้น 8', 'ชั้นที่ 12', 'ชั้นที่ : 12', 'ชั้น 24A', 'ชั้น G'
    # ป้องกันไม่ให้จับ 'พื้นที่ชั้น' และไม่ให้จับตัวเลขตามด้วยหน่วยพื้นที่
    m_unit = re.search(r'(?<!พื้นที่)ชั้น(?:ที่)?\s*[:\s]*([0-9]{1,2}[A-Za-z]?|G|M|B[1-9]?|ลอย)\b(?!\s*(?:ห้อง(?:นอน|น้ำ|ครัว|ส้วม)|ตร\.?ม|ตรม|ตารางเมตร|sqm|sq\.?m|วา|ตร\.?ว|ตารางวา))', cleaned, re.IGNORECASE)
    if m_unit:
        val_u = m_unit.group(1).strip()
        if not (val_u.isdigit() and int(val_u) >= 80):
            return val_u
        
    # 2. รูปแบบภาษาอังกฤษ: Floor 12, 12th Floor, Fl. 12
    m_en = re.search(r'\b(?:floor|fl\.?)\s*[:\s]*([0-9]{1,2}[A-Za-z]?)\b(?!\s*(?:area|size|sqm|ตร\.?ม))', cleaned, re.IGNORECASE) or re.search(r'\b([0-9]{1,2})(?:st|nd|rd|th)\s*floor\b', cleaned, re.IGNORECASE)
    if m_en:
        val_en = m_en.group(1).strip()
        if not (val_en.isdigit() and int(val_en) >= 80):
            return val_en
            
    # 3. กรณีคอนโด Low Rise ระบุจำนวนชั้นอาคาร เช่น 'อาคาร 8 ชั้น' หรือ 'ตึก 8 ชั้น' (จำกัดไม่เกิน 8 ชั้น)
    m_story_condo = re.search(r'(?:อาคาร|ตึก|สูง)\s*([1-8])\s*ชั้น(?!\s*(?:ที่|ตร\.?ม|ตรม|ตารางเมตร))', cleaned)
    if m_story_condo:
        val = m_story_condo.group(1).strip()
        return f"{val} ชั้น"
        
    return None

PERSON_TITLES_PATTERN = re.compile(
    r'(?<![ทน])นาย|'
    r'นางสาว|น\.ส\.|'
    r'นาง(?!รอง|เลิ้ง)|'
    r'เด็กชาย|เด็กหญิง|ด\.ช\.|ด\.ญ\.|'
    r'ว่าที่\s*ร้อย|ว่าที่\s*ร\.ต\.|ว่าที่\s*ร\.ท\.|ว่าที่\s*ร\.อ\.|'
    r'(?:ร้อย|พัน|พล)\s*(?:ตรี|โท|เอก)|'
    r'(?:ร้อย|พัน|พล)\s*ตำรวจ\s*(?:ตรี|โท|เอก)|'
    r'(?:ร|พ|พล)\.ต\.[อตท]\.|'
    r'ดาบตำรวจ|ด\.ต\.|จ่าสิบ|จ\.ส\.[อตท]\.|สิบตำรวจ|ส\.ต\.[อตท]\.|'
    r'นายแพทย์|แพทย์หญิง|นพ\.|พญ\.|'
    r'ผศ\.|รศ\.|ศ\.ดร\.|'
    r'มิสเตอร์|มิส|มิสซิส|\b(?:mr|mrs|miss|ms)(?:\.\s+|\.(?=$)|\s+)'
    , re.IGNORECASE
)

PERSON_START_PATTERN = re.compile(
    r'^(?:'
    r'นาย|นางสาว|น\.ส\.|นาง(?!รอง|เลิ้ง)|เด็กชาย|เด็กหญิง|ด\.ช\.|ด\.ญ\.|'
    r'ว่าที่\s*ร้อย|ว่าที่\s*ร\.ต\.|ว่าที่\s*ร\.ท\.|ว่าที่\s*ร\.อ\.|'
    r'(?:ร้อย|พัน|พล)\s*(?:ตรี|โท|เอก)|'
    r'(?:ร้อย|พัน|พล)\s*ตำรวจ\s*(?:ตรี|โท|เอก)|'
    r'(?:ร|พ|พล)\.ต\.[อตท]\.|'
    r'ดาบตำรวจ|ด\.ต\.|จ่าสิบ|จ\.ส\.[อตท]\.|สิบตำรวจ|ส\.ต\.[อตท]\.|'
    r'นายแพทย์|แพทย์หญิง|นพ\.|พญ\.|'
    r'ผศ\.|รศ\.|ศ\.ดร\.|'
    r'มิสเตอร์|มิส|มิสซิส|\b(?:mr|mrs|miss|ms)(?:\.\s+|\.(?=$)|\s+)'
    r')'
    , re.IGNORECASE
)

def clean_plaintiff_name(name):
    """
    ดึงข้อมูลโจทก์และกรองชื่อบุคคลธรรมดาออก (PDPA Privacy Compliance)
    เช่น หากขึ้นต้นหรือมีชื่อจริงคน (นาย, นาง, นางสาว, น.ส., ยศตำรวจ/ทหาร, คำนำหน้านามบุคคล) ให้เว้นว่างไว้ ""
    หากเป็นนิติบุคคล/สถาบัน/ธนาคาร/สหกรณ์ แต่มีผู้รับมอบอำนาจ (เช่น โดยนาย... หรือ ,นาย... ผู้ร้อง) 
    จะตัดเฉพาะส่วนชื่อบุคคลออก คงเหลือชื่อนิติบุคคลไว้
    """
    if name is None or pd.isna(name):
        return ''
    s = str(name).strip()
    if s.lower() in ['none', 'null', 'nan', '<na>', '-', '']:
        return ''
    
    # ข้อยกเว้นสำหรับตำแหน่งหน่วยงานรัฐ เช่น นายกเทศมนตรี, นายกองค์การบริหารส่วนตำบล
    if s.startswith(('นายกเทศมนตรี', 'นายกองค์การ', 'นายกสมาคม')):
        return s
        
    # 1. บุคคลธรรมดา: ขึ้นต้นด้วยคำนำหน้านามบุคคล -> เว้นว่างไว้ ""
    if PERSON_START_PATTERN.search(s):
        return ''
        
    # 2. กรณีเป็นนิติบุคคล/หน่วยงาน แต่มีต่อท้ายด้วยผู้รับมอบอำนาจ/ผู้ร้อง/โจทก์ร่วมที่เป็นบุคคล
    # ให้ตัดส่วนชื่อบุคคลออก (เช่น ' โดยนาย...', ' ,นางสาว... ผู้ร้อง')
    s_cleaned = re.sub(
        r'[\s,]+(?:โดย\s*)?(?:'
        r'นาย|นางสาว|น\.ส\.|นาง(?!รอง|เลิ้ง)|เด็กชาย|เด็กหญิง|ด\.ช\.|ด\.ญ\.|'
        r'ว่าที่\s*ร้อย|ว่าที่\s*ร\.ต\.|ว่าที่\s*ร\.ท\.|ว่าที่\s*ร\.อ\.|'
        r'(?:ร้อย|พัน|พล)\s*(?:ตรี|โท|เอก)|'
        r'(?:ร้อย|พัน|พล)\s*ตำรวจ\s*(?:ตรี|โท|เอก)|'
        r'(?:ร|พ|พล)\.ต\.[อตท]\.|(?:ร|พ|พล)\.[อตท]\.|'
        r'ดาบตำรวจ|ด\.ต\.|จ่าสิบ|จ\.ส\.[อตท]\.|สิบตำรวจ|ส\.ต\.[อตท]\.|'
        r'นายแพทย์|แพทย์หญิง|นพ\.|พญ\.|'
        r'ผศ\.|รศ\.|ศ\.ดร\.|'
        r'มิสเตอร์|มิส|มิสซิส|\b(?:mr|mrs|miss|ms)(?:\.\s+|\.(?=$)|\s+)'
        r').*$',
        '',
        s,
        flags=re.IGNORECASE
    )
    s_cleaned = s_cleaned.strip()
    
    # 3. ตรวจสอบว่ายังมีคำนำหน้านามบุคคลหลงเหลืออยู่หรือไม่ (ยกเว้นคำที่สะกดคล้าย เช่น ทนาย, ทนายความ, นครนายก)
    s_check = s_cleaned.replace('ทนายความ', '').replace('ทนาย', '').replace('นครนายก', '')
    if PERSON_TITLES_PATTERN.search(s_check):
        return ''
        
    return s_cleaned

