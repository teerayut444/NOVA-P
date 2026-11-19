# -*- coding: utf-8 -*-
"""
clean_project_util.py
โมดูลความเร็วสูงสำหรับ Clean, จัดมาตรฐาน (Standardization) และจับคู่ (Harmonization)
ชื่อโครงการอสังหาริมทรัพย์สำหรับ All Asset NPA Dashboard และระบบ SAM Analytics
"""

import os
import sys
import re
import argparse
import threading
import unicodedata
import pandas as pd
import numpy as np

_AMPHOE_LOCK = threading.RLock()

# Force UTF-8 stdout on Windows console
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ==============================================================================
# 1. CANONICAL BRAND DICTIONARY (ตารางจับคู่แบรนด์มาตรฐาน 100+ แบรนด์)
# ==============================================================================
BRAND_REPLACEMENTS = [
    # --- Ananda Development ---
    (r'(?i)(?:\b(?:ideo|idio)\s*mobi|ไอดีโอ\s*โมบิ)\s*สุขุมวิท\s*[-–—]?\s*(?:อีสท์?เกต|eastgate)(?:\s*บางนา)?', 'ไอดีโอ โมบิ สุขุมวิท อีสท์เกต'),
    (r'(?i)\b(?:ideo|idio)\s*mobi\b|ไอดีโอ\s*โมบิ|ไอดิโอ\s*โมบิ', 'ไอดีโอ โมบิ'),
    (r'(?i)\b(?:ideo|idio)\s*q\b|ไอดีโอ\s*คิว|ไอดิโอ\s*คิว', 'ไอดีโอ คิว'),
    (r'(?i)\b(?:ideo|idio)\s*o2\b|ไอดีโอ\s*โอทู(?:\s*บางนา)?|ไอดิโอ\s*โอทู', 'ไอดีโอ โอทู'),
    (r'(?i)\b(?:ideo|idio)\s*tha\s*phra\b|ไอดีโอ\s*ท่าพระ', 'ไอดีโอ ท่าพระ'),
    (r'(?i)\b(?:ideo|idio)\s*rama\s*9\b|ไอดีโอ\s*พระราม\s*9', 'ไอดีโอ พระราม 9'),
    (r'(?i)\b(?:ideo|idio)\b|ไอดิโอ|ไอดีโอ', 'ไอดีโอ'),
    (r'(?i)\belio\s*del\s*ray\b|เอลลิโอ\s*เดล\s*เรย์', 'เอลลิโอ เดล เรย์'),
    (r'(?i)\belio\s*del\s*nest\b|เอลลิโอ\s*เดล\s*เนสท์', 'เอลลิโอ เดล เนสท์'),
    (r'(?i)\belio\b|เอลิโอ|เอลลิโอ', 'เอลลิโอ'),
    (r'(?i)\bashton\b|แอชตัน', 'แอชตัน'),
    (r'(?i)\bpieamsuk\b|เปี่ยมสุข', 'เปี่ยมสุข'),
    (r'(?i)\bunio\b|ยูนิโอ', 'ยูนิโอ'),
    (r'(?i)\bartale\b|อาร์เทล', 'อาร์เทล'),
    (r'(?i)\bairi\b|แอริ', 'แอริ'),

    # --- LPN Development (Lumpini) ---
    (r'(?i)\blumpini\s*condotown\b|\blumpini\s*condo\s*town\b|ลุมพินี\s*คอนโดทาวน์|ลุมพินีคอนโดทาวน์|\blpn\s*condotown\b', 'ลุมพินี คอนโดทาวน์'),
    (r'(?i)\blumpini\s*ville\b|ลุมพินี\s*วิลล์|ลุมพินีวิลล์|\blpn\s*ville\b', 'ลุมพินี วิลล์'),
    (r'(?i)\blumpini\s*park\b|ลุมพินี\s*พาร์ค|ลุมพินีพาร์ค|\blpn\s*park\b', 'ลุมพินี พาร์ค'),
    (r'(?i)\blumpini\s*place\b|ลุมพินี\s*เพลส|ลุมพินีเพลส|\blpn\s*place\b', 'ลุมพินี เพลส'),
    (r'(?i)\blumpini\s*suite\b|ลุมพินี\s*สวีท|ลุมพินีสวีท|\blpn\s*suite\b', 'ลุมพินี สวีท'),
    (r'(?i)\blumpini\s*townplace\b|ลุมพินี\s*ทาวน์เพลส', 'ลุมพินี ทาวน์เพลส'),
    (r'(?i)\blumpini\s*townville\b|ลุมพินี\s*ทาวน์วิลล์', 'ลุมพินี ทาวน์วิลล์'),
    (r'(?i)\blumpini\s*seaview\b|ลุมพินี\s*ซีวิว', 'ลุมพินี ซีวิว'),
    (r'(?i)\blumpini\s*mega\s*city\b|ลุมพินี\s*เมกะซิตี้', 'ลุมพินี เมกะซิตี้'),
    (r'(?i)\blumpini\b|\blpn\b|ลุมพินี', 'ลุมพินี'),

    # --- Sansiri ---
    (r'(?i)\bthe\s*monument\b|เดอะ\s*โมนูเมนต์', 'เดอะ โมนูเมนต์'),
    (r'(?i)\bthe\s*line\b|เดอะ\s*ไลน์|เดอะไลน์', 'เดอะ ไลน์'),
    (r'(?i)\bthe\s*base\b|เดอะ\s*เบส|เดอะเบส', 'เดอะ เบส'),
    (r'(?i)\bdcondo\b|\bd\s*condo\b|ดี\s*คอนโด|ดีคอนโด', 'ดีคอนโด'),
    (r'(?i)\boka\s*haus\b|โอกะ\s*เฮ้าส์', 'โอกะ เฮ้าส์'),
    (r'(?i)\bkawa\s*haus\b|คาวะ\s*เฮ้าส์', 'คาวะ เฮ้าส์'),
    (r'(?i)\btaka\s*haus\b|ทากะ\s*เฮ้าส์', 'ทากะ เฮ้าส์'),
    (r'(?i)\bhasu\s*haus\b|ฮาสุ\s*เฮ้าส์', 'ฮาสุ เฮ้าส์'),
    (r'(?i)\bxt\b|เอ็กซ์ที', 'เอ็กซ์ที'),
    (r'(?i)\bsiri\s*place\b|สิริ\s*เพลส|สิริเพลส', 'สิริ เพลส'),
    (r'(?i)\bsiri\s*avenue\b|สิริ\s*อเวนิว', 'สิริ อเวนิว'),
    (r'(?i)\bhabitia\b|ฮาบิเทีย', 'ฮาบิเทีย'),
    (r'(?i)\bsaransiri\b|สราญสิริ', 'สราญสิริ'),
    (r'(?i)\bburasiri\b|บุราสิริ', 'บุราสิริ'),
    (r'(?i)\bsetthasiri\b|เศรษฐสิริ', 'เศรษฐสิริ'),
    (r'(?i)\bnarasiri\b|นาราสิริ', 'นาราสิริ'),
    (r'(?i)\bkanasiri\b|คณาสิริ', 'คณาสิริ'),
    (r'(?i)\banasiri\b|อณาสิริ', 'อณาสิริ'),
    (r'(?i)\bbugaan\b|บูก้าน', 'บูก้าน'),

    # --- AP Thailand ---
    (r'(?i)\blife\s*bangkok\s*boulevard\b|ไลฟ์\s*บางกอก\s*บูเลอวาร์ด', 'ไลฟ์ บางกอก บูเลอวาร์ด'),
    (r'(?i)\baspire\b|แอสปายร์|แอสปาย', 'แอสปาย'),
    (r'(?i)\brhythm\b|ริทึ่ม|ริธึ่ม', 'ริธึ่ม'),
    (r'(?i)\bthe\s*address\b|ดิ\s*แอดเดรส', 'ดิ แอดเดรส'),
    (r'(?i)\bgrande\s*pleno\b|แกรนด์\s*พลีโน่', 'แกรนด์ พลีโน่'),
    (r'(?i)\bpleno\s*town\b|พลีโน่\s*ทาวน์', 'พลีโน่ ทาวน์'),
    (r'(?i)\bpleno\b|พลีโน่', 'พลีโน่'),
    (r'(?i)\bthe\s*city\b|เดอะ\s*ซิตี้|เดอะซิตี้', 'เดอะ ซิตี้'),
    (r'(?i)\bthe\s*palazzo\b|เดอะ\s*พาลาซโซ', 'เดอะ พาลาซโซ'),
    (r'(?i)\bcentro\b|เซนโทร', 'เซนโทร'),
    (r'(?i)\bbaan\s*klang\s*muang\b|บ้านกลางเมือง', 'บ้านกลางเมือง'),
    (r'(?i)\bbaan\s*klang\s*krung\b|บ้านกลางกรุง', 'บ้านกลางกรุง'),
    (r'(?i)\bclasse\b|คลาสเซ่', 'คลาสเซ่'),
    (r'(?i)\bmoden\b|โมเดน', 'โมเดน'),
    (r'(?i)\bapitown\b|อภิทาวน์', 'อภิทาวน์'),
    (r'(?i)\bcool\s*condo\b|คูลคอนโด|คูล\s*คอนโด', 'คูลคอนโด'),

    # --- Pruksa Real Estate ---
    (r'(?i)\bplum\s*condo\b|พลัม\s*คอนโด|พลัมคอนโด', 'พลัม คอนโด'),
    (r'(?i)\bplum\b|พลัม', 'พลัม คอนโด'),
    (r'(?i)\bchapter\s*one\b|แชปเตอร์\s*วัน|แชปเตอร์วัน', 'แชปเตอร์ วัน'),
    (r'(?i)\bthe\s*privacy\b|เดอะ\s*ไพรเวซี่|เดอะไพรเวซี่', 'เดอะ ไพรเวซี่'),
    (r'(?i)\bprivacy\b|ไพรเวซี่', 'เดอะ ไพรเวซี่'),
    (r'(?i)\bfuse\b|ฟิวส์', 'ฟิวส์'),
    (r'(?i)\bivy\b|ไอวี่', 'ไอวี่'),
    (r'(?i)\bpruksa\s*ville\b|พฤกษาวิลล์|พฤกษา\s*วิลล์', 'พฤกษาวิลล์'),
    (r'(?i)\bbaan\s*pruksa\b|บ้านพฤกษา', 'บ้านพฤกษา'),
    (r'(?i)\bthe\s*connect\b|เดอะ\s*คอนเนคท์|เดอะ\s*คอนเนค|เดอะคอนเนค', 'เดอะ คอนเนค'),
    (r'(?i)\bpassorn\b|ภัสสร', 'ภัสสร'),
    (r'(?i)\bcity\s*sense\b|ซิตี้เซนส์|ซิตี้\s*เซนส์', 'ซิตี้เซนส์'),
    (r'(?i)\bpatio\b|พาทิโอ', 'พาทิโอ'),
    (r'(?i)\bvillette\s*lite\b|วิลเลต\s*ไลท์|วิลเลตไลท์', 'วิลเลต ไลท์'),
    (r'(?i)\bvillette\s*city\b|วิลเลต\s*ซิตี้|วิลเลตซิตี้', 'วิลเลต ซิตี้'),
    (r'(?i)\bthe\s*gallery\b|เดอะ\s*แกลเลอรี่', 'เดอะ แกลเลอรี่'),
    (r'(?i)\bthe\s*palm\b|เดอะ\s*ปาล์ม', 'เดอะ ปาล์ม'),
    (r'(?i)\bpruksakan\b|พฤกษากาญจน์', 'พฤกษากาญจน์'),
    (r'(?i)\bpruksa\b|พฤกษา', 'พฤกษา'),

    # --- Supalai ---
    (r'(?i)\bsupalai\s*city\s*resort\b|ศุภาลัย\s*ซิตี้\s*รีสอร์ท', 'ศุภาลัย ซิตี้ รีสอร์ท'),
    (r'(?i)\bsupalai\s*city\s*home\b|\bcity\s*home\b|ซิตี้\s*โฮม|ซิตี้โฮม', 'ซิตี้ โฮม'),
    (r'(?i)\bsupalai\s*parkville\b|ศุภาลัย\s*พาร์ควิลล์', 'ศุภาลัย พาร์ควิลล์'),
    (r'(?i)\bsupalai\s*gardenville\b|ศุภาลัย\s*การ์เด้นวิลล์', 'ศุภาลัย การ์เด้นวิลล์'),
    (r'(?i)\bsupalai\s*park\b|ศุภาลัย\s*ปาร์ค|ศุภาลัยปาร์ค', 'ศุภาลัย ปาร์ค'),
    (r'(?i)\bsupalai\s*vista\b|ศุภาลัย\s*วิสต้า', 'ศุภาลัย วิสต้า'),
    (r'(?i)\bsupalai\s*prima\b|ศุภาลัย\s*พรีมา', 'ศุภาลัย พรีมา'),
    (r'(?i)\bsupalai\s*cute\b|ศุภาลัย\s*คิวท์', 'ศุภาลัย คิวท์'),
    (r'(?i)\bsupalai\s*river\b|ศุภาลัย\s*ริเวอร์', 'ศุภาลัย ริเวอร์'),
    (r'(?i)\bsupalai\s*premier\b|ศุภาลัย\s*พรีเมียร์', 'ศุภาลัย พรีเมียร์'),
    (r'(?i)\bsupalai\s*oriental\b|ศุภาลัย\s*โอเรียนทัล', 'ศุภาลัย โอเรียนทัล'),
    (r'(?i)\bsupalai\s*veranda\b|ศุภาลัย\s*เวอเรนด้า', 'ศุภาลัย เวอเรนด้า'),
    (r'(?i)\bsupalai\s*monte\b|ศุภาลัย\s*มอนเต้', 'ศุภาลัย มอนเต้'),
    (r'(?i)\bsupalai\s*bella\b|ศุภาลัย\s*เบลล่า', 'ศุภาลัย เบลล่า'),
    (r'(?i)\bsupalai\s*ville\b|ศุภาลัย\s*วิลล์', 'ศุภาลัย วิลล์'),
    (r'(?i)\bsupalai\s*moda\b|ศุภาลัย\s*โมด้า', 'ศุภาลัย โมด้า'),
    (r'(?i)\bsupalai\s*essence\b|ศุภาลัย\s*เอสเซ้นส์', 'ศุภาลัย เอสเซ้นส์'),
    (r'(?i)\bsupalai\s*loft\b|ศุภาลัย\s*ลอฟท์', 'ศุภาลัย ลอฟท์'),
    (r'(?i)\bsupalai\b|ศุภาลัย', 'ศุภาลัย'),

    # --- Land & Houses ---
    (r'(?i)\bthe\s*key\b|เดอะ\s*คีย์|เดอะคีย์', 'เดอะ คีย์'),
    (r'(?i)\bthe\s*room\b|เดอะ\s*รูม|เดอะรูม', 'เดอะ รูม'),
    (r'(?i)\bthe\s*bangkok\b|เดอะ\s*บางกอก', 'เดอะ บางกอก'),
    (r'(?i)\bmantana\s*garden\s*suite\b|มัณฑนา\s*การ์เด้นสวีท', 'มัณฑนา การ์เด้นสวีท'),
    (r'(?i)\bmantana\b|มัณฑนา', 'มัณฑนา'),
    (r'(?i)\bchaiyapruek\b|ชัยพฤกษ์', 'ชัยพฤกษ์'),
    (r'(?i)\bprueklada\b|พฤกษ์ลดา', 'พฤกษ์ลดา'),
    (r'(?i)\bsiwalee\b|สีวลี', 'สีวลี'),
    (r'(?i)\bladawan\b|ลดาวัลย์', 'ลดาวัลย์'),
    (r'(?i)\bnantawan\b|นันทวัน', 'นันทวัน'),
    (r'(?i)\bvillaggio\b|วิลลาจจิโอ', 'วิลลาจจิโอ'),
    (r'(?i)\bindy\b|อินดี้', 'อินดี้'),
    (r'(?i)\bpruekpirom\b|พฤกษ์ภิรมย์', 'พฤกษ์ภิรมย์'),

    # --- SC Asset ---
    (r'(?i)\bgrand\s*bangkok\s*boulevard\b|แกรนด์\s*บางกอก\s*บูเลอวาร์ด', 'แกรนด์ บางกอก บูเลอวาร์ด'),
    (r'(?i)\bbangkok\s*boulevard\b|บางกอก\s*บูเลอวาร์ด|บางกอกบูเลอวาร์ด', 'บางกอก บูเลอวาร์ด'),
    (r'(?i)\bthe\s*crest\b|เดอะ\s*เครสท์', 'เดอะ เครสท์'),
    (r'(?i)\bchambers\b|แชมเบอร์ส', 'แชมเบอร์ส'),
    (r'(?i)\bcentric\b|เซ็นทริค|เซนทริค', 'เซ็นทริค'),
    (r'(?i)\bvenue\b|(?<!อ)เวนิว', 'เวนิว'),
    (r'(?i)\bpave\b|เพฟ', 'เพฟ'),
    (r'(?i)\bverve\b|เวิร์ฟ', 'เวิร์ฟ'),
    (r'(?i)\bgranada\b|กรานาด้า', 'กรานาด้า'),
    (r'(?i)\bheadquarters\b|เฮดควอเทอร์ส', 'เฮดควอเทอร์ส'),
    (r'(?i)\bworkplace\b|เวิร์คเพลส', 'เวิร์คเพลส'),
    (r'(?i)\bv\s*compound\b|วี\s*คอมพาวด์', 'วี คอมพาวด์'),

    # --- Origin Property ---
    (r'(?i)\bknightsbridge\b|ไนท์บริดจ์|ไนท์บิดจ์', 'ไนท์บริดจ์'),
    (r'(?i)\bnotting\s*hill\b|น็อตติ้ง\s*ฮิลล์|น็อตติ้งฮิลล์', 'น็อตติ้ง ฮิลล์'),
    (r'(?i)\bkensington\b|เคนซิงตัน', 'เคนซิงตัน'),
    (r'(?i)\bpark\s*origin\b|พาร์ค\s*ออริจิ้น', 'พาร์ค ออริจิ้น'),
    (r'(?i)\bthe\s*origin\b|ดิ\s*ออริจิ้น', 'ดิ ออริจิ้น'),
    (r'(?i)\bgrand\s*britania\b|แกรนด์\s*บริทาเนีย', 'แกรนด์ บริทาเนีย'),
    (r'(?i)\bbritania\b|บริทาเนีย', 'บริทาเนีย'),
    (r'(?i)\bbelgravia\b|เบลกราเวีย', 'เบลกราเวีย'),
    (r'(?i)\bb\s*loft\b|บี\s*ลอฟท์', 'บี ลอฟท์'),

    # --- Quality Houses (Q.House) ---
    (r'(?i)\bq\s*house\b|\bq\.house\b|คิว\s*เฮ้าส์|คิวเฮ้าส์', 'คิว เฮ้าส์'),
    (r'(?i)\bcasa\s*ville\b|คาซ่า\s*วิลล์|คาซ่าวิลล์', 'คาซ่า วิลล์'),
    (r'(?i)\bcasa\s*condo\b|คาซ่า\s*คอนโด|คาซ่าคอนโด', 'คาซ่า คอนโด'),
    (r'(?i)\bcasa\s*city\b|คาซ่า\s*ซิตี้|คาซ่าซิตี้', 'คาซ่า ซิตี้'),
    (r'(?i)\bcasa\s*premium\b|คาซ่า\s*พรีเมี่ยม', 'คาซ่า พรีเมี่ยม'),
    (r'(?i)\bcasa\b|คาซ่า', 'คาซ่า'),
    (r'(?i)\bthe\s*trust\b|เดอะ\s*ทรัสต์|เดอะทรัสต์', 'เดอะ ทรัสต์'),
    (r'(?i)\bgusto\b|กัสโต้', 'กัสโต้'),
    (r'(?i)\bladdarom\b|ลัดดารมย์', 'ลัดดารมย์'),
    (r'(?i)\bvararom\b|วรารมย์', 'วรารมย์'),

    # --- Property Perfect ---
    (r'(?i)\bperfect\s*masterpiece\b|เพอร์เฟค\s*มาสเตอร์พีซ|เพอร์เฟคมาสเตอร์พีซ', 'เพอร์เฟค มาสเตอร์พีซ'),
    (r'(?i)\bperfect\s*place\b|เพอร์เฟค\s*เพลส|เพอร์เฟคเพลส', 'เพอร์เฟค เพลส'),
    (r'(?i)\bperfect\s*park\b|เพอร์เฟค\s*พาร์ค|เพอร์เฟคพาร์ค', 'เพอร์เฟค พาร์ค'),
    (r'(?i)\bmetro\s*sky\b|เมโทร\s*สกาย|เมโทรสกาย', 'เมโทร สกาย'),
    (r'(?i)\bthe\s*sky\b|เดอะ\s*สกาย', 'เดอะ สกาย'),
    (r'(?i)\bi\s*condo\b|\bi-condo\b|\bicondo\b|ไอ-คอนโด|ไอคอนโด', 'ไอคอนโด'),
    (r'(?i)\bmodi\s*villa\b|โมดิ\s*วิลล่า', 'โมดิ วิลล่า'),

    # --- Sena Development ---
    (r'(?i)\bsena\s*kith\b|เสนา\s*คิทท์|เสนาคิทท์', 'เสนา คิทท์'),
    (r'(?i)\bthe\s*niche\b|เดอะ\s*นิช|เดอะนิช', 'เดอะ นิช'),
    (r'(?i)\bniche\s*mono\b|นิช\s*โมโน', 'นิช โมโน'),
    (r'(?i)\bniche\s*pride\b|นิช\s*ไพรด์', 'นิช ไพรด์'),
    (r'(?i)\bsena\s*park\b|เสนา\s*พาร์ค', 'เสนา พาร์ค'),
    (r'(?i)\bsena\s*ville\b|เสนา\s*วิลล์', 'เสนา วิลล์'),
    (r'(?i)\bflexi\b|เฟล็กซี่', 'เฟล็กซี่'),

    # --- Noble Development ---
    (r'(?i)\bnoble\s*revolve\b|โนเบิล\s*รีวอลฟ์', 'โนเบิล รีวอลฟ์'),
    (r'(?i)\bnoble\s*refine\b|โนเบิล\s*รีไฟน์', 'โนเบิล รีไฟน์'),
    (r'(?i)\bnoble\s*solo\b|โนเบิล\s*โซโล', 'โนเบิล โซโล'),
    (r'(?i)\bnoble\s*ploenchit\b|โนเบิล\s*เพลินจิต', 'โนเบิล เพลินจิต'),
    (r'(?i)\bnoble\s*around\b|โนเบิล\s*อราวน์', 'โนเบิล อราวน์'),
    (r'(?i)\bnoble\s*remix\b|โนเบิล\s*รีมีกซ์', 'โนเบิล รีมีกซ์'),
    (r'(?i)\bnoble\s*lite\b|โนเบิล\s*ไลท์', 'โนเบิล ไลท์'),
    (r'(?i)\bnue\s*noble\b|\bnue\s*condo\b|นิว\s*โนเบิล|นิว\s*คอนโด', 'นิว โนเบิล'),
    (r'(?i)\bnoble\b|โนเบิล', 'โนเบิล'),

    # --- Regent Green Power ---
    (r'(?i)\bregent\s*home\b|รีเจ้นท์\s*โฮม|รีเจ้นท์โฮม', 'รีเจ้นท์ โฮม'),
    (r'(?i)\bregent\s*orchid\b|รีเจ้นท์\s*ออคิด', 'รีเจ้นท์ ออคิด'),
    (r'(?i)\bregent\b|รีเจ้นท์', 'รีเจ้นท์'),

    # --- Grand Unity ---
    (r'(?i)\bu\s*delight\b|ยู\s*ดีไลท์|ยูดีไลท์', 'ยู ดีไลท์'),
    (r'(?i)\bciela\b|เซียล่า', 'เซียล่า'),
    (r'(?i)\bdenim\b|เดนิม', 'เดนิม'),
    (r'(?i)\bde\s*lapis\b|เดอ\s*ลาพีส', 'เดอ ลาพีส'),

    # --- Areeya Property ---
    (r'(?i)\ba\s*space\s*me\b|เอ\s*สเปซ\s*มี', 'เอ สเปซ มี'),
    (r'(?i)\ba\s*space\b|\baspace\b|เอ\s*สเปซ|เอสเปซ', 'เอ สเปซ'),
    (r'(?i)\bthe\s*colors\b|เดอะ\s*คัลเลอร์ส', 'เดอะ คัลเลอร์ส'),
    (r'(?i)\bthe\s*village\b|เดอะ\s*วิลเลจ', 'เดอะ วิลเลจ'),
    (r'(?i)\bcomo\b|โคโม่', 'โคโม่'),
    (r'(?i)\bareeya\b|อารียา', 'อารียา'),

    # --- Major Development ---
    (r'(?i)\bmaestro\b|มาเอสโตร', 'มาเอสโตร'),
    (r'(?i)\bmetris\b|เมทริส', 'เมทริส'),
    (r'(?i)\bm\s*jatujak\b|เอ็ม\s*จตุจักร', 'เอ็ม จตุจักร'),

    # --- Singha Estate ---
    (r'(?i)\bthe\s*esse\b|ดิ\s*เอส', 'ดิ เอส'),
    (r'(?i)\bsantiburi\b|สันติบุรี', 'สันติบุรี'),
    (r'(?i)\bsiraninn\b|ศิรนินทร์', 'ศิรนินทร์'),

    # --- Other Famous Condos & Villages ---
    (r'(?i)\bthe\s*tree\b|เดอะ\s*ทรี|เดอะทรี', 'เดอะ ทรี'),
    (r'(?i)\bchuan\s*chuen\b|ชวนชื่น', 'ชวนชื่น'),
    (r'(?i)\bsammakorn\b|สัมมากร', 'สัมมากร'),
    (r'(?i)\bchalermnit\b|เฉลิมนิจ', 'เฉลิมนิจ'),
    (r'(?i)\bmanhattan\b|แมนฮัตตัน', 'แมนฮัตตัน'),
    (r'(?i)\bmanor\b|แมเนอร์', 'แมเนอร์'),
    (r'(?i)\blife\b|ไลฟ์', 'ไลฟ์'),
]

# ==============================================================================
# 1.5 BILINGUAL LOCATION REPLACEMENTS (แปลงชื่อทำเลภาษาอังกฤษยอดนิยมเป็นภาษาไทย)
# ==============================================================================
LOCATION_REPLACEMENTS = [
    (r'(?i)\bsukhumvit\b', 'สุขุมวิท'),
    (r'(?i)\bphaholyothin\b|\bphahonyothin\b|\bphahon\s*yothin\b', 'พหลโยธิน'),
    (r'(?i)\bchaengwattana\b|\bchaeng\s*wattana\b', 'แจ้งวัฒนะ'),
    (r'(?i)\brama\s*9\b', 'พระราม 9'),
    (r'(?i)\brama\s*8\b', 'พระราม 8'),
    (r'(?i)\brama\s*7\b', 'พระราม 7'),
    (r'(?i)\brama\s*6\b', 'พระราม 6'),
    (r'(?i)\brama\s*5\b', 'พระราม 5'),
    (r'(?i)\brama\s*4\b', 'พระราม 4'),
    (r'(?i)\brama\s*3\b', 'พระราม 3'),
    (r'(?i)\brama\s*2\b', 'พระราม 2'),
    (r'(?i)\bsathorn\b|\bsatorn\b', 'สาทร'),
    (r'(?i)\basoke\b|\basok\b', 'อโศก'),
    (r'(?i)\bratchada\b|\bratchadaphisek\b|\brajchadaphisek\b', 'รัชดา'),
    (r'(?i)\bladprao\b|\blat\s*phrao\b', 'ลาดพร้าว'),
    (r'(?i)\bsrinakarin\b|\bsrinagarindra\b', 'ศรีนครินทร์'),
    (r'(?i)\bbangna\b|\bbang\s*na\b', 'บางนา'),
    (r'(?i)\bphetkasem\b', 'เพชรเกษม'),
    (r'(?i)\brattanathibet\b', 'รัตนาธิเบศร์'),
    (r'(?i)\bthonglor\b|\bthong\s*lo\b', 'ทองหล่อ'),
    (r'(?i)\bekkamai\b|\bekamai\b', 'เอกมัย'),
    (r'(?i)\bari\b|\baree\b', 'อารีย์'),
    (r'(?i)\bphayathai\b|\bphyathai\b', 'พญาไท'),
    (r'(?i)\bsamyan\b|\bsam\s*yan\b', 'สามย่าน'),
    (r'(?i)\bsilom\b', 'สีลม'),
    (r'(?i)\bchula\b', 'จุฬา'),
    (r'(?i)\bbangwa\b|\bbang\s*wa\b', 'บางหว้า'),
    (r'(?i)\bbangkae\b|\bbang\s*khae\b', 'บางแค'),
    (r'(?i)\bbangyai\b|\bbang\s*yai\b', 'บางใหญ่'),
    (r'(?i)\bbangbuathong\b|\bbang\s*bua\s*thong\b', 'บางบัวทอง'),
    (r'(?i)\btiwanon\b', 'ติวานนท์'),
    (r'(?i)\bngamwongwan\b|\bngam\s*wong\s*wan\b', 'งามวงศ์วาน'),
    (r'(?i)\bwongwianyai\b|\bwongwian\s*yai\b', 'วงเวียนใหญ่'),
    (r'(?i)\bkrungthonburi\b|\bkrung\s*thon\s*buri\b', 'กรุงธนบุรี'),
    (r'(?i)\bcharoennakhon\b|\bcharoen\s*nakhon\b', 'เจริญนคร'),
    (r'(?i)\bcharoenkrung\b|\bcharoen\s*krung\b', 'เจริญกรุง'),
    (r'(?i)\bprannok\b', 'พรานนก'),
    (r'(?i)\bonnut\b|\bon\s*nut\b', 'อ่อนนุช'),
    (r'(?i)\budomsuk\b|\budom\s*suk\b', 'อุดมสุข'),
    (r'(?i)\bbearing\b', 'แบริ่ง'),
    (r'(?i)\bsamrong\b', 'สำโรง'),
    (r'(?i)\brangsit\b', 'รังสิต'),
    (r'(?i)\blamlukka\b|\blam\s*luk\s*ka\b', 'ลำลูกกา'),
    (r'(?i)\bsaimai\b|\bsai\s*mai\b', 'สายไหม'),
    (r'(?i)\bramintra\b|\bram\s*intra\b', 'รามอินทรา'),
    (r'(?i)\bramkhamhaeng\b', 'รามคำแหง'),
    (r'(?i)\bpattanakarn\b', 'พัฒนาการ'),
    (r'(?i)\bsuanluang\b|\bsuan\s*luang\b', 'สวนหลวง'),
    (r'(?i)\bdonmueang\b|\bdon\s*mueang\b', 'ดอนเมือง'),
    (r'(?i)\bkaset\b', 'เกษตร'),
    (r'(?i)\bnawamin\b', 'นวมินทร์'),
    (r'(?i)\bratchaphruek\b', 'ราชพฤกษ์'),
    (r'(?i)\bkanlapaphruek\b', 'กัลปพฤกษ์'),
    (r'(?i)\bkanchanaphisek\b', 'กาญจนาภิเษก'),
    (r'(?i)\bpinklao\b|\bpin\s*klao\b', 'ปิ่นเกล้า'),
    (r'(?i)\bcharan\b|\bcharansanitwong\b', 'จรัญสนิทวงศ์'),
    (r'(?i)\bwongsawang\b|\bwong\s*sawang\b', 'วงศ์สว่าง'),
    (r'(?i)\btaopoon\b|\btao\s*poon\b', 'เตาปูน'),
    (r'(?i)\bbangsue\b|\bbang\s*sue\b', 'บางซื่อ'),
    (r'(?i)\bbangpo\b|\bbang\s*po\b', 'บางโพ'),
    (r'(?i)\bbangplad\b|\bbang\s*phlat\b', 'บางพลัด'),

    # --- Transit, Landmark & Project Types ---
    (r'(?i)\binterchange\b', 'อินเตอร์เชนจ์'),
    (r'(?i)\bstation\b', 'สเตชั่น'),
    (r'(?i)\bresidences?\b', 'เรสซิเดนซ์'),
    (r'(?i)\bprime\b', 'ไพร์ม'),
    (r'(?i)\bgrand\b|\bgrande\b', 'แกรนด์'),
    (r'(?i)\bpark\b', 'พาร์ค'),
    (r'(?i)\bville\b', 'วิลล์'),
    (r'(?i)\bplace\b', 'เพลส'),
    (r'(?i)\bsuites?\b', 'สวีท'),
    (r'(?i)\btown\b', 'ทาวน์'),
    (r'(?i)\bview\b', 'วิว'),
    (r'(?i)\briverside\b', 'ริเวอร์ไซด์'),
    (r'(?i)\briver\b', 'ริเวอร์'),
    (r'(?i)\bheights?\b', 'ไฮท์ส'),
    (r'(?i)\bgardens?\b', 'การ์เด้น'),
    (r'(?i)\bcampus\b', 'แคมปัส'),
    (r'(?i)\bresort\b', 'รีสอร์ท')
]

# Compile regular expressions for efficiency
COMPILED_BRAND_PATTERNS = [(re.compile(p), rep) for p, rep in BRAND_REPLACEMENTS]
COMPILED_LOCATION_PATTERNS = [(re.compile(p), rep) for p, rep in LOCATION_REPLACEMENTS]

# ==============================================================================
# 2. PREFIX & SUFFIX PATTERNS (รูปแบบตัดคำขยะ/คำนำหน้า/คำต่อท้าย)
# ==============================================================================
PROP_TYPES = [
    'บ้านเดี่ยว', 'บ้านแฝด', 'บ้านพักอาศัย', 'บ้านทรงไทย', 'บ้านไม้',
    'ทาวน์เฮ้าส์', 'ทาวน์เฮ้า่ส', 'ทาวน์เฮาส์', 'ทาวน์โฮม', 'โฮมออฟฟิศ',
    'อาคารพาณิชย์', 'ตึกแถว', 'อาคารพาณิช', 'อาคารตึกแถว',
    'ที่ดินเปล่า', 'ที่ดินจัดสรร', 'ที่ดินพร้อมสิ่งปลูกสร้าง', 'ที่ดิน',
    'ห้องชุดพักอาศัย', 'ห้องชุด', 'คอนโดมิเนียม', 'คอนโดมีเนียม', 'คอนโด',
    'อพาร์ทเม้นท์', 'อพาร์ทเมนท์', 'หอพักอาศัย', 'หอพัก', 'โรงแรม', 'รีสอร์ท',
    'โรงงาน', 'โกดัง', 'โกดังสินค้า', 'สิ่งปลูกสร้าง', 'อาคารชุด', 'อาคารสำนักงาน', 'อาคาร'
]

PROP_REGEX = r'(?:' + '|'.join(PROP_TYPES) + r')'
STOREY_REGEX = r'(?:\d+\s*ชั้น(?:\s*ครึ่ง)?|ชั้นเดียว|ชั้นครึ่ง|\d+\s*ชั้นครึ่ง)'

BUILDING_DESC_JUNK = [
    'บ้านครึ่งตึกครึ่งไม้', 'ครึ่งตึกครึ่งไม้', 'บ้านตึก', 'บ้านไม้ชั้นเดียว',
    'โครงสร้างอาคาร', 'สิ่งปลูกสร้าง', 'อาคารพาณิชย์ 2', 'อาคารพาณิชย์ 3'
]

GENERIC_PREFIX_REGEX = re.compile(
    r'^(?:โครงการหมู่บ้าน|หมู่บ้านโครงการ|ในโครงการหมู่บ้าน|ในโครงการ|โครงการ|อาคารชุด|คอนโดมิเนียม|คอนโดมีเนียม|มีเนียม|คอนโด|หมู่บ้านจัดสรร|หมู่บ้าน|โคงการ|โครการ|มบ\.|ม\.|บ\.)\s*',
    re.IGNORECASE
)

STANDALONE_PROP_TYPE_PREFIX = re.compile(
    r'^(?:ห้องชุดพักอาศัย|ที่พักอาศัย|พักอาศัย|ห้องชุด|คอนโดมิเนียม|คอนโดมีเนียม|มีเนียม|คอนโด|ทาวน์เฮ้าส์|ทาวน์เฮ้า่ส|ทาวน์เฮาส์|ทาวน์โฮม|บ้านเดี่ยว|บ้านแฝด|อาคารพาณิชย์|ตึกแถว|ที่ดินเปล่า|ที่ดินจัดสรร|ที่ดินพร้อมสิ่งปลูกสร้าง|ที่ดิน|อาคารชุด)\s+',
    re.IGNORECASE
)

BANK_DESC_PREFIX_REGEX = re.compile(
    r'^(?:บ้านเดี่ยว|บ้านแฝด|บ้านพักอาศัย|บ้าน|คอนโดมิเนียม|คอนโดมีเนียม|มีเนียม|คอนโด|ห้องชุดพักอาศัย|ห้องชุด|ทาวน์เฮ้าส์|ทาวน์เฮ้า่ส|ทาวน์เฮาส์|ทาวน์โฮม|อาคารพาณิชย์|ตึกแถว|ที่ดินเปล่า|ที่ดินจัดสรร|ที่ดิน|อาคารชุด)?\s*'
    r'(?:\d+\s*ชั้น(?:\s*ครึ่ง)?|ชั้นเดียว|ชั้นครึ่ง)?\s*'
    r'(?:ใน|ติด)?(?:โครงการหมู่บ้าน|หมู่บ้านโครงการ|โครงการ|หมู่บ้าน|โคงการ|โครการ|อาคารชุด|มบ\.|ม\.|บ\.)\s*',
    re.IGNORECASE
)

CONDITION_SUFFIX_REGEX = re.compile(
    r'(\s*:\s*(?:ปรับปรุง|ปรับปรุงแล้ว|สภาพดี|รอการปรับปรุง|ขายตามสภาพ).*$|\s*\(.*ปรับปรุง.*\)$|\s*\*.*\*$)',
    re.IGNORECASE
)

AD_PREFIX_REGEX = re.compile(
    r'^(?:ขาย|ให้เช่า|เช่า|และให้เช่า|และขาย|ขายด่วน|ด่วน|ขายด่วนมาก|ต้องการขาย|ฝากขาย|รับสร้างบ้าน|ขาย/เช่า|ขายหรือให้เช่า|ถูก|าย|เซ้ง)\s*'
    r'(?:บ้านเดี่ยว|บ้านแฝด|บ้านพักอาศัย|บ้าน|ทาวน์เฮ้าส์|ทาวน์เฮ้า่ส|ทาวน์เฮาส์|ทาวน์โฮม|ทาวน์|โฮมออฟฟิศ|อาคารพาณิชย์|ตึกแถว|อาคารตึกแถว|อาคารสำนักงาน|อาคาร|ที่ดินพร้อมสิ่งปลูกสร้าง|ที่ดินจัดสรร|ที่ดินเปล่า|ที่ดิน|ห้องชุดพักอาศัย|ห้องชุด|คอนโดมิเนียม|คอนโดมีเนียม|คอนโด|อพาร์ทเม้นท์|อพาร์ทเมนท์|หอพัก|โกดังสินค้า|โกดัง|โรงงาน|ตึก|สิทธิ์)?(?:\s*|\b)',
    re.IGNORECASE
)

STOREY_ONLY_REGEX = re.compile(
    r'^(?:บ้าน|บ้านเดี่ยว|บ้านแฝด|คอนโด|ห้องชุด|ทาวน์เฮ้าส์|ทาวน์โฮม|วิลล่า|อาคารพาณิชย์|ตึกแถว|อาคาร)?\s*(?:\d+\s*ชั้น(?:\s*ครึ่ง)?|ชั้นเดียว|ชั้นครึ่ง)$',
    re.IGNORECASE
)
BEDROOM_ONLY_REGEX = re.compile(
    r'^(?:บ้าน|คอนโด|คอนโดมิเนียม|ห้องชุด|ทาวน์เฮ้าส์|ทาวน์โฮม|วิลล่า|อาคารพาณิชย์|ตึกแถว|อพาร์ทเมนท์)?\s*'
    r'(?:\d+|\d+-\d+)?\s*(?:-)?\s*(?:ห้องนอน|ห้องน้ำ|bedroom|bed room|bathroom|ห้องนอน/|ห้องนอน-)(?:\s*\d*\s*(?:ห้องน้ำ|bathroom)?)?$',
    re.IGNORECASE
)

AREA_SPEC_REGEX = re.compile(
    r'(\d+\s*(?:ไร่|งาน|ตารางวา|ตร\.ว|ตารางเมตร|ตร\.ม|ตรม|sq\.?m|sqm)|เนื้อที่\s*\d+|ขนาดพื้นที่\s*\d+|หน้ากว้าง\s*\d+)',
    re.IGNORECASE
)

CONTACT_PHRASE_REGEX = re.compile(
    r'(?:เจ้าของขายเอง|งดรับนายหน้า|ราคาถูกเพียง|พร้อมอยู่|แถมฟรี|เฟอร์ครบ|ติดต่อ\s*\d|โทร\s*\d|0\d{1,2}[- ]?\d{3,4}[- ]?\d{3,4}|line\s*id)',
    re.IGNORECASE
)

BANK_PORTAL_COMPANIES = {
    'ktb', 'bam', 'sam', 'ghb', 'gsb', 'kbank', 'scb', 'cimb', 'ttb', 'bay', 'tmb', 'uob',
    'lhbank', 'kkp', 'tisco', 'chayo', 'chayo555', 'baania', 'ddproperty', 'livinginsider',
    'zmyhome', 'nayoo', 'led', 'npa'
}

GENERIC_PROJECT_NAMES = BANK_PORTAL_COMPANIES | {
    '', 'nan', 'none', 'null', 'undefined', '-', '--', '---', '.', '..', '...', '?', '#name?',
    'ไม่มีชื่อ', 'ไม่ระบุ', 'ไม่ระบุชื่อ', 'ทรัพย์สิน npa', 'ทรัพย์ npa', 'npa', 'โครงการ',
    '(ต้นฉบับชำรุด)', 'นอกโครงการ', 'ไม่ปรากฏชื่อโครงการ', 'ไม่มีชื่อโครงการ', 'หมู่บ้านไม่มีชื่อ',
    '(ไม่มีชื่อ)', 'ม.ไม่มีชื่อ', 'ไม่มีชื่อโครงการ/สิ่งปลูกสร้าง', 'สิ่งปลูกสร้าง',
    'ไม่พบโครงการ', '1 ห้อง', '2 ห้อง', '3 ห้อง', '4 ห้อง', '5 ห้อง', 'ห้อง', 'ห้องนอน', 'ห้องน้ำ',
    '2.5 ชั้น', '3.5 ชั้น', '4.5 ชั้น', 'ชั้นเดียว', 'ชั้นครึ่ง', 'ชั้นลอย',
    'ด่วน', 'ขายด่วน', 'แบ่งขายได้', 'พร้อมผู้เช่า', 'พร้อมอยู่', 'ราคาถูก', 'หลุดจำนอง', 'ขายขาดทุน',
    'บ้าน', 'บ้านเดี่ยว', 'บ้านแฝด', 'ทาวน์เฮ้าส์', 'ทาวน์โฮม', 'คอนโด', 'คอนโดมิเนียม', 'ที่ดิน', 'ที่ดินเปล่า',
    'อาคารพาณิชย์', 'ตึกแถว', 'ห้องชุด', 'ห้องชุดพักอาศัย', 'อพาร์ทเมนท์', 'อพาร์ทเม้นท์', 'หอพัก', 'โรงงาน', 'โกดัง',
    'house', 'condo', 'townhouse', 'villa', 'land', 'apartment',
    'house for sale', 'condo for sale', 'villa for sale', 'land for sale', 'commercial',
    'ตึก 2 ชั้น', 'ตึก 3 ชั้น', 'บ้าน 2 ชั้น', 'บ้าน 1 ชั้น', 'บ้าน 3 ชั้น', 'บ้านตึก', 'เดี่ยว', 'เฮ้าส์', 'พาณิชย์', 'แฝด', 'แถว', 'ตึก', 'ชุด', 'วิลล่า', 'ทาวน์',
    'ทาวน์เฮาส์', 'ทาวน์เฮ้าส์', 'ทาวโฮม', 'ทาวน์โฮม', 'ทาวเฮาส์', 'ทาวเฮ้าส์', 'โฮมออฟฟิศ', 'home office',
    'ปรับปรุงใหม่', 'ปรับปรุงแล้ว', 'สร้างเอง', 'บ้านสร้างเอง', 'สภาพดี', 'พร้อมอยู่', 'ห้องเปล่า', 'มือหนึ่ง', 'มือสอง',
    'หลุดจำนอง', 'ขายขาดทุน', 'ราคาถูก', 'ด่วน', 'ขายด่วน', 'ติดถนน', 'ริมถนน', 'แปลงสวย', 'แปลงใหญ่', 'ทำเลดี', 'ทำเลทอง',
    'พูลวิลล่า', 'pool villa', 'และค้าขายได้', 'อยู่อาศัยและค้าขายได้', 'ลึก', 'สวย', 'สวยๆ', 'ในเมือง', 'นอกเมือง', 'ใจกลางเมือง', 'ทำเลในเมือง', 'ถูกที่สุดในโครงการ', 'บ้าน ห้องเช่า', 'ห้องเช่า', 'พร้อมที่จอดรถ', 'ทำเลศักยภาพ'
}

ALL_PROVINCES = [
    'กรุงเทพมหานคร', 'กรุงเทพฯ', 'กรุงเทพ', 'กทม.', 'กทม', 'กระบี่', 'กาญจนบุรี', 'กาฬสินธุ์',
    'กำแพงเพชร', 'ขอนแก่น', 'จันทบุรี', 'ฉะเชิงเทรา', 'ชลบุรี', 'ชัยนาท', 'ชัยภูมิ',
    'ชุมพร', 'เชียงราย', 'เชียงใหม่', 'ตรัง', 'ตราด', 'ตาก', 'นครนายก', 'นครปฐม',
    'นครพนม', 'นครราชสีมา', 'นครศรีธรรมราช', 'นครสวรรค์', 'นนทบุรี', 'นราธิวาส',
    'น่าน', 'บึงกาฬ', 'บุรีรัมย์', 'ปทุมธานี', 'ประจวบคีรีขันธ์', 'ปราจีนบุรี', 'ปัตตานี',
    'พระนครศรีอยุธยา', 'อยุธยา', 'พะเยา', 'พังงา', 'พัทลุง', 'พิจิตร', 'พิษณุโลก',
    'เพชรบุรี', 'เพชรบูรณ์', 'แพร่', 'ภูเก็ต', 'มหาสารคาม', 'มุกดาหาร', 'แม่ฮ่องสอน',
    'ยโสธร', 'ยะลา', 'ร้อยเอ็ด', 'ระนอง', 'ระยอง', 'ราชบุรี', 'ลพบุรี', 'ลำปาง',
    'ลำพูน', 'เลย', 'ศรีสะเกษ', 'สกลนคร', 'สงขลา', 'สตูล', 'สมุทรปราการ',
    'สมุทรสงคราม', 'สมุทรสาคร', 'สระแก้ว', 'สระบุรี', 'สิงห์บุรี', 'สุโขทัย',
    'สุพรรณบุรี', 'สุราษฎร์ธานี', 'สุรินทร์', 'หนองคาย', 'หนองบัวลำภู', 'อ่างทอง',
    'อำนาจเจริญ', 'อุดรธานี', 'อุตรดิตถ์', 'อุทัยธานี', 'อุบลราชธานี'
]

COMMON_PROJECT_PROVINCES = ALL_PROVINCES

_ALL_AMPHOES_SET = None

def get_all_amphoes() -> set:
    """
    โหลดรายชื่ออำเภอ/เขตทั้งหมด 923 แห่งในประเทศไทยเพื่อตรวจสอบชื่อทำเลที่ปลอมเป็นชื่อโครงการ
    """
    global _ALL_AMPHOES_SET
    if _ALL_AMPHOES_SET is not None:
        return _ALL_AMPHOES_SET

    with _AMPHOE_LOCK:
        if _ALL_AMPHOES_SET is not None:
            return _ALL_AMPHOES_SET
        mapping = set()
        try:
            import json
            candidates = []
            if getattr(sys, '_MEIPASS', None):
                candidates.append(os.path.join(sys._MEIPASS, "districts.geojson"))
            base_dir = os.path.dirname(os.path.abspath(__file__))
            candidates.append(os.path.join(base_dir, "districts.geojson"))
            candidates.append(os.path.join(os.path.dirname(base_dir), "districts.geojson"))
            candidates.append(os.path.join(os.path.dirname(base_dir), "data", "districts.geojson"))
            candidates.append(os.path.join(os.path.dirname(base_dir), "Py Scraper", "districts.geojson"))

            geojson_path = next((p for p in candidates if os.path.exists(p)), None)
            if geojson_path:
                with open(geojson_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for feat in data.get("features", []):
                    p = feat.get("properties", {})
                    a = str(p.get("amp_th") or "").strip()
                    if a:
                        mapping.add(a)
                        if a.startswith("เมือง"):
                            mapping.add(a[5:].strip())
        except Exception:
            pass
        _ALL_AMPHOES_SET = mapping
        return _ALL_AMPHOES_SET

# ==============================================================================
# 3. CORE NORMALIZATION ENGINE (ฟังก์ชันแกนหลัก)
# ==============================================================================

def normalize_phase_notation(text: str) -> str:
    """
    จัดรูปแบบ Phase / เฟส / โครงการ 1 ให้เป็นมาตรฐานเดียวกัน: 'เฟส 1'
    """
    if not text:
        return ""
    s = text
    s = re.sub(r'(?i)\bphase\s*(\d+)\b', r'เฟส \1', s)
    s = re.sub(r'เฟส\s*(\d+)', r'เฟส \1', s)
    s = re.sub(r'โครงการ\s*(\d+)', r'โครงการ \1', s)
    s = re.sub(r'(?i)\bphase\s*i\b', 'เฟส 1', s)
    s = re.sub(r'(?i)\bphase\s*ii\b', 'เฟส 2', s)
    s = re.sub(r'(?i)\bphase\s*iii\b', 'เฟส 3', s)
    return s


def clean_trailing_ad_noise(name: str) -> str:
    """
    ตัดคำโฆษณา/สเปก/ทำเลต่อท้ายชื่อโครงการ เช่น 'ราคาก่อนโอน...', '2ห้องนอน...', 'ใกล้ BTS...', '(ตำแหน่งดีที่สุด)'
    """
    if not name:
        return ""
    s = str(name).strip()
    
    # 0. ตัดรหัสประกาศ/ตัวเลขอ้างอิงนำหน้า เช่น "46063 – ...", "12345 - ..."
    s = re.sub(r'^\d{4,8}\s*[-–—]\s*', '', s)
    
    # 1. ตัดอีโมจิและสัญลักษณ์ตกแต่งพิเศษ
    s = re.sub(r'[\U00010000-\U0010ffff\u200d\u2300-\u23ff\u2b50\u2728\u2700-\u27bf\u2600-\u26ff]+.*$', '', s)
    
    # 2. ตัดวงเล็บท้ายชื่อ (ตัดวงเล็บที่ปิดเรียบร้อยที่อยู่ท้ายสตริง หรือวงเล็บที่เปิดทิ้งไว้)
    s = re.sub(r'[\s\-_/]*\([^)]*\)\s*$', '', s)
    s = re.sub(r'[\s\-_/]*\[[^\]]*\]\s*$', '', s)
    s = re.sub(r'[\s\-_/]*\([^)]*$', '', s)
    s = re.sub(r'[\s\-_/]*\[[^\]]*$', '', s)
    
    # 3. ตัดคำโฆษณา สเปกห้อง และการระบุทำเลต่อท้าย
    ad_noise_pat = (
        r'[\s\-_/]+(?:'
        r'ราคา[^\s]*|ถูกที่[^\s]*|ดีที่[^\s]*|ตำแหน่ง[^\s]*|หลังโอน[^\s]*|ก่อนโอน[^\s]*|'
        r'พร้อมอยู่[^\s]*|พร้อมเข้าอยู่[^\s]*|พร้อมผู้เช่า[^\s]*|เฟอร์[^\s]*|เครื่องใช้ไฟฟ้า[^\s]*|แต่งครบ[^\s]*|แถม[^\s]*|ฟรี[^\s]*|(?:ลดราคา|ลดพิเศษ|ลดสุด|ลดด่วน|ลดเหลือ)[^\s]*|ด่วน[^\s]*|'
        r'ตกแต่ง[^\s]*|บ้านสวย|ต้นซอย|ทำเล[^\s]*|ชั้นสูง[^\s]*|วิวสวย[^\s]*|ลมดี|ห้อง\s*(?:duplex|มุม|ริม)[^\s]*|'
        r'แบ่งสัดส่วน[^\s]*|โควต้า[^\s]*|ชาวต่างชาติ[^\s]*|for\s*sale|for\s*rent|'
        r'\d+\s*(?:ห้องนอน|ห้องน้ำ|นอน|น้ำ|ห้อง|bed|bath|br|studio)|studio|'
        r'(?:บ้านเดี่ยว|บ้านแฝด|ทาวน์โฮม|ทาวน์เฮ้าส์|อาคารพาณิชย์|ตึกแถว|ที่ดิน)(?:\s*\d*\s*ชั้น)?|'
        r'(?:หลังมุม|แปลงมุม|ห้องมุม|ห้องริม|แปลงสวย|ทำเลทอง|ทำเลดี|ซทำเลดี|รีโนเวท|ตกแต่งใหม่|ต่อเติม|น่าอยู่)|'
        r'(?:ใกล้|ใกล้กับ|ติดกับ|ตรงข้าม|เยื้อง)(?:\s+.*)?|(?:หลังมุม|หลังริม|หน้าโครงการ|หน้ากว้าง|ติดถนน|ติดรถไฟฟ้า|ติดMRT|ติดBTS|ติดทะเล|ติดหาด)(?:\s+.*)?|'
        r'(?:บิ้วอิน|บิวท์อิน|บิลท์อิน|built\s*in|พร้อมเฟอร์|พร้อมอยู่|เครื่องใช้ไฟฟ้า|แถมแอร์|แถมเฟอร์|สภาพดี|รีโนเวท|ปรับปรุง|สร้างเอง|ต่อเติม|เนื้อที่|ขนาด|อยู่อาศัยและค้าขายได้)|'
        r'(?:(?:ราคา|เพียง|ลดเหลือ)\s*[\d,.]+(?:\s*(?:ล้านบาท|ล้าน|แสน|บาท|.-|บ\.))?|[\d,.]+\s*(?:ล้านบาท|ล้าน|แสน|บาท|.-|บ\.))|'
        r'(?:ซอย|ซ\.|แยก)\s*\d+'
        r').*$'
    )
    s = re.sub(ad_noise_pat, '', s, flags=re.I)
    
    # จัดช่องว่างและอักขระขอบนอก
    s = re.sub(r"\s+", " ", s).strip(' :-/,(._#!–—"“”’«»[]\'')
    if s.count(')') > s.count('('):
        s = re.sub(r'\)+$', '', s).strip()
    if s.count(']') > s.count('['):
        s = re.sub(r'\]+$', '', s).strip()
    return s

def clean_sam_project_name(raw_name, _allow_split: bool = True) -> str:
    """
    ทำความสะอาดและจัดมาตรฐานชื่อโครงการอสังหาริมทรัพย์ (โดยเฉพาะสำหรับ SAM และเทียบกับสถาบันอื่น)
    
    คุณสมบัติ:
    - รองรับชื่อสองภาษา (Bilingual Dual Titles: 'EN : TH' หรือ 'TH / EN') โดยเลือกชื่อไทยที่สมบูรณ์ที่สุด
    - สกัดชื่อโครงการจากในวงเล็บหรือคำโฆษณา (เช่น 'ขายคอนโด (ไอดีโอโมบิวงศ์สว่าง-อินเตอร์เชนจ์)')
    - กู้คืนชื่อโครงการจริงจากข้อความบรรยาย (Embedded Project Recovery เช่น 'ขายคอนโด 1 ห้อง ชั้น 4 ในโครงการมาราเกช...')
    - ดักกรองคำขยะ / สเปกห้อง / จำนวนชั้น / คำโฆษณา / ทำเล ที่ไม่ใช่ชื่อโครงการออกเป็นค่าว่าง ""
    - ตัดคำนำหน้าประเภททรัพย์ (เช่น 'ห้องชุด ไอดีโอ...', 'บ้านเดี่ยว 2 ชั้น โครงการ...')
    - ตัดเลขชั้น/อาคาร/ห้อง ในวงเล็บท้ายชื่อ (เช่น '[ชั้น 26 ]')
    - จัดระเบียบคำที่เขียนติดกัน เช่น 'ไอดีโอโมบิ' -> 'ไอดีโอ โมบิ'
    - จัดการยัติภังค์ 'วงศ์สว่าง - อินเตอร์เชนจ์' -> 'วงศ์สว่าง-อินเตอร์เชนจ์'
    """
    if not raw_name or pd.isna(raw_name):
        return ""
    
    n = str(raw_name).strip()
    n = unicodedata.normalize('NFKC', n)
    # Fix Thai Sara Am decomposition caused by NFKC (\u0e4d\u0e32 -> \u0e33)
    n = n.replace('\u0e4d\u0e32', '\u0e33')
    nl = n.lower()
    
    # 1. ขยะชัดเจน / Placeholder / ทำเลโดดๆ ที่ไม่ใช่ชื่อโครงการ
    if nl in GENERIC_PROJECT_NAMES or len(n) <= 1:
        return ""
    if nl in ALL_PROVINCES or f"จ.{nl}" in ALL_PROVINCES or nl in [f"เมือง{p}" for p in ALL_PROVINCES]:
        return ""
    all_amp = get_all_amphoes()
    if nl in all_amp or re.sub(r'^(?:เมือง|อำเภอ|เขต)\s*', '', nl) in all_amp:
        return ""
    for bj in BUILDING_DESC_JUNK:
        if n.startswith(bj):
            return ""
    for prefix_junk in ['undefined', 'ไม่มีชื่อ', 'โครงการไม่มีชื่อ', 'ไม่ระบุ', 'นอกโครงการ', 'ไม่พบโครงการ']:
        if nl.startswith(prefix_junk):
            return ""

    # ตัดข้อความสเปกที่ดิน/คูหา/แปลง และการระบุติดถนน/คลอง
    if re.search(r'^\d+\s*(?:แปลง|คูหา|ห้อง|ยูนิต|ไร่|งาน|ตารางวา|ตร\.?ว|ตร\.?ม)', n):
        return ""
    if re.search(r'^ติด(?:กับ)?(?:ถนน|ทางหลวง|ซอย|คลอง|คอลง|แม่น้ำ|ลำน้ำ|ราง|ทางรถไฟ|บีทีเอส|bts|mrt)', n, re.I):
        return ""
    if re.search(r'^(?:พร้อม|แถม|มี|ฟรี)\s*(?:ที่จอดรถ|ที่จอด|เฟอร์|สระ|ลิฟท์|รปภ|แอร์|ผู้เช่า|สิ่งอำนวยความสะดวก|คนเช่า)', n):
        return ""
    if re.search(r'^(?:พูลวิลล่า|pool villa|บ้านพักตากอากาศ)\s*(?:ที่สวย|ทำเลดี|สวย|หรู|ราคาถูก|ขายด่วน)', n, re.I):
        return ""
    if re.search(r'^(?:ในเมือง|นอกเมือง|ใจกลางเมือง|ทำเลในเมือง)', n):
        rem_city = re.sub(r'^(?:ในเมือง|นอกเมือง|ใจกลางเมือง|ทำเลในเมือง)\s*', '', n).strip()
        if not rem_city or rem_city in ALL_PROVINCES or rem_city in get_all_amphoes() or 'ถนน' in rem_city:
            return ""

    # ดักกรองข้อความที่เป็นข้อความโฆษณา/สเปก/ประเภททรัพย์ล้วนๆ ที่ไม่มีชื่อแบรนด์หรือคำบ่งชี้โครงการ
    pure_ad_prefixes = r'^(?:แปลงมุมสวย|ที่ดินเปล่า|ขายที่ดิน|เซ้งตึกแถว|ตึกแถว|อาคารพาณิชย์|ทาวน์เฮ้าส์|ทาวน์โฮม|บ้านเดี่ยว|มีชั้นลอย|และโกดัง|ใกล้สนามกีฬา|ทำเลดี|ทำเลทอง|เปล่า\s*ตำบล|พาณิชย์\s*\d|เดี่ยวทำเลดี|วารินชำราบ|ราคา\s*\d)'
    if re.search(pure_ad_prefixes, n, re.I):
        has_brand = any(p.search(n) for p, _ in COMPILED_BRAND_PATTERNS)
        has_proj = bool(re.search(r'(?:โครงการ|หมู่บ้าน|คอนโด|เอื้ออาทร|เคหะ|วิลล่า|การ์เด้น|พาร์ค|เรสซิเดนซ์|เพลส|ทาวน์|ซิตี้|ฮิลล์|วิว|โฮม)\s*[ก-๙a-zA-Z0-9]', n))
        if not has_brand and not has_proj:
            return ""

    # ดักกรองคำคุณศัพท์โฆษณาที่ไม่มีชื่อโครงการจริง
    if re.search(r'(?:ดีไซน์สวย|วิวสวย|เงียบสงบ|สาเหตุที่ขาย|เดินทางสะดวก|ราคาถูก|ขายด่วน|พร้อมผู้เช่า|สภาพดี)', n):
        has_brand = any(p.search(n) for p, _ in COMPILED_BRAND_PATTERNS)
        has_proj = bool(re.search(r'(?:โครงการ|หมู่บ้าน|คอนโด|เอื้ออาทร|เคหะ|วิลล่า|การ์เด้น|พาร์ค|เรสซิเดนซ์|เพลส|ทาวน์|ซิตี้|ฮิลล์|วิว|โฮม)\s*[ก-๙a-zA-Z0-9]', n))
        if not has_brand and not has_proj:
            return ""

    # ดักกรองการรวมชื่อทำเล/ถนน 3 จุดขึ้นไปโดยไม่มีชื่อแบรนด์
    words = n.split()
    if len(words) >= 4 and not any(p.search(n) for p, _ in COMPILED_BRAND_PATTERNS):
        loc_words = sum(1 for w in words if any(loc in w for loc in ['งามวงศ์วาน', 'เกษตร', 'นวมินทร์', 'ประชาชื่น', 'วิภาวดี', 'แจ้งวัฒนะ', 'รัชดา', 'ลาดพร้าว', 'สุขุมวิท', 'สาทร', 'สีลม', 'พระราม', 'บางนา', 'รามอินทรา', 'รังสิต', 'เพชรเกษม', 'จรัญ']))
        if loc_words >= 3:
            return ""

    # ตัดเลขหรือเศษวงเล็บนำหน้า เช่น "29)", "18)", "1433)"
    n = re.sub(r'^\d+\s*[\)\]\}]\s*', '', n)
    n = re.sub(r'[\(\[\{]\s*\d+\s*$', '', n)
    if not n:
        return ""

    # 2. ตัวเลขล้วน เครื่องหมายล้วน หรือช่วงตัวเลข เช่น 1-4, 3.5, 4.5
    if re.match(r'^\d+(?:[\s\-_/.]+\d+)?$', n) or re.match(r'^[.\-_/*+?#! @$%^&*()+=~`:;]+$', n):
        return ""
        
    # Relative Location phrases (เช่น "ใกล้สถานี BTS...", "ตรงข้ามเซ็นทรัล...")
    if re.match(r'^(?:ใกล้|ตรงข้าม|หลัง|เชิงสะพาน|ปากซอย)\s*(?:สถานี|bts|mrt|ทางด่วน|ถนน|ซอย|ห้าง|เซ็นทรัล|เดอะมอลล์|โลตัส|บิ๊กซี|ม\.|มหาวิทยาลัย|รพ\.|โรงเรียน|โรงพยาบาล|สนามบิน|นิคม|วัด|สะพาน|แยก|ตลาด|สวน)', n, re.I):
        return ""
        
    # Administrative phrases only (เช่น "ต.รวมโชค", "อำเภอเมือง")
    if re.match(r'^(?:ต\.|ตำบล|อ\.|อำเภอ|จ\.|จังหวัด|เขต|แขวง)\s*[ก-๙a-zA-Z0-9\s]+$', n):
        return ""

    # Ad words without brand/project (e.g. "ด่วน", "ขายด่วน", "แบ่งขายได้", "พร้อมผู้เช่า", "ราคาถูก")
    if re.match(r'^(?:ด่วน|ขายด่วน|สำหรับ\s*ขาย|แบ่งขายได้|พร้อมผู้เช่า|ราคาถูก|ขาย/เช่า)(?:\s+|$)', n, re.I):
        if 'ทางด่วน' not in n and not any(p.search(n) for p, _ in COMPILED_BRAND_PATTERNS):
            return ""

    # Room / spec only starting (e.g. "3 ห้องนอน 3 ห้องน้ำ...", "1 ห้อง...", "เดี่ยว 1 ชั้น ราคา...")
    if re.match(r'^(?:\d+\s*(?:ห้องนอน|ห้องน้ำ|ห้อง|ชั้น|ตร\.?ว|ตร\.?ม|ตารางวา|ไร่|งาน)|ชั้น\s*\d+|เดี่ยว\s*\d+\s*ชั้น|เฮ้าส์\s*\d+\s*ชั้น|พาณิชย์\s*\d+\s*ชั้น)', n, re.I):
        if not re.search(r'(?:ใน|ติด)?(?:โครงการหมู่บ้าน|หมู่บ้านโครงการ|ในโครงการ|โครงการ|หมู่บ้าน|โคงการ|โครการ|(?<!ก)(?<!ตร\.)(?<!ลบ\.)(?<!ซ)(?<!ช)(?:มบ\.|ม\.)(?!(?:ใกล้|ตรงข้าม|ติด|เยื้อง|รังสิต|กรุงเทพ|ธรรมศาสตร์|เกษตร|มหิดล|ศรีนคริน|หอการค้า)))\s*[ก-๙a-zA-Z0-9]', n):
            return ""

    # 3. จัดการกรณีชื่อสองภาษาเชื่อมด้วยโคลอนหรือสแลช เช่น "The Line Jatujak-Mochit : เดอะ ไลน์ จตุจักร - หมอชิต, กรุงเทพ"
    if _allow_split:
        for sep in [' : ', ':', ' / ', ' | ']:
            if sep in n:
                parts = [p.strip() for p in n.split(sep) if p.strip()]
                if len(parts) >= 2:
                    cleaned_parts = [clean_sam_project_name(p, _allow_split=False) for p in parts]
                    valid_parts = [cp for cp in cleaned_parts if cp and cp.lower() not in GENERIC_PROJECT_NAMES]
                    if valid_parts:
                        # ให้ความสำคัญกับพาร์ทที่มีตัวอักษรภาษาไทยมากที่สุด (ชื่อไทยสมบูรณ์)
                        best_part = max(valid_parts, key=lambda x: (len(re.findall(r'[ก-๙]', x)), -abs(len(x)-15)))
                        return best_part

    # 4. ตรวจหาส่วนโครงการที่ฝังอยู่ในข้อความโฆษณา (Embedded Project Recovery)
    # เช่น "ขายคอนโด 1 ห้อง ชั้น 4 ในโครงการมาราเกช หัวหิน เรสซิเดนเซส ราคา 12.50 ล้านบาท ในอำเภอหัวหิน"
    m_proj = re.search(r'(?:^|[^\d\s/]|(?<=\d)\s*|\s+)(?:ใน|ติด)?(?:โครงการหมู่บ้าน|หมู่บ้านโครงการ|ในโครงการ|โครงการ|หมู่บ้าน|โคงการ|โครการ|(?<!ก)(?<!ตร\.)(?<!ลบ\.)(?<!ซ)(?<!ช)(?:มบ\.|ม\.)(?=[ก-๙a-zA-Z])(?!(?:ใกล้|ตรงข้าม|ติด|เยื้อง|รังสิต|กรุงเทพ|ธรรมศาสตร์|เกษตร|มหิดล|ศรีนคริน|หอการค้า)))\s*([ก-๙a-zA-Z0-9\s\-_()]+)', n)
    if m_proj:
        inner_proj = m_proj.group(1).strip()
        # ตัดส่วนท้ายที่เป็นราคาหรือทำเลของประกาศ
        inner_proj = re.sub(r'[\s\-_/]+ราคา\s*[\d\.,]+\s*(?:ล้านบาท|บาท|ลบ|.-)?.*$', '', inner_proj, flags=re.I)
        inner_proj = re.sub(r'[\s\-_/]+ใน(?:อำเภอ|เขต|ตำบล|จังหวัด|จ\.|อ\.|ต\.).*$', '', inner_proj, flags=re.I)
        inner_proj = re.sub(r'[\s\-_/]+ชั้น\s*\d+.*$', '', inner_proj, flags=re.I)
        inner_proj = inner_proj.strip()
        if len(inner_proj) >= 2 and inner_proj.lower() not in GENERIC_PROJECT_NAMES and inner_proj not in ALL_PROVINCES and inner_proj not in all_amp:
            c_inner = clean_sam_project_name(inner_proj, _allow_split=False)
            if c_inner and c_inner.lower() not in GENERIC_PROJECT_NAMES:
                return c_inner

    # 5. ดึงชื่อโครงการจากในวงเล็บหากมีคำนำหน้าโฆษณา เช่น "ขายคอนโด (ไอดีโอโมบิวงศ์สว่าง-อินเตอร์เชนจ์)"
    m_paren = re.search(r'[\(\[\{]([^\)\]\}]+)[\)\]\}]', n)
    if m_paren:
        inner = m_paren.group(1).strip()
        # กรองวงเล็บสภาพทรัพย์ / ชั้น / แปลงมุม ออก
        if re.match(r'^(?:แปลงมุม|ห้องริม|หลังริม|ห้องมุม|ขายตามสภาพ|สภาพดี|ปรับปรุงแล้ว|พร้อมอยู่|แปลงที่\s*\d+|ชั้น\s*\d+|\d+\s*ชั้น).*$', inner, re.I):
            n = re.sub(r'[\(\[\{][^\)\]\}]+[\)\]\}]', '', n).strip()
        elif AD_PREFIX_REGEX.match(n) or any(b in inner.lower() for b in ['ไอดีโอ', 'ไอดิโอ', 'ideo', 'idio', 'ลุมพินี', 'lpn', 'lumpini', 'พลัม', 'plum', 'ศุภาลัย', 'supalai', 'เดอะ', 'the']):
            c_inner = clean_sam_project_name(inner, _allow_split=False)
            if c_inner and c_inner.lower() not in GENERIC_PROJECT_NAMES:
                return c_inner

    # 6. ตัดข้อความโฆษณาเริ่มต้น (เช่น "ขายคอนโด...", "ให้เช่าบ้าน...")
    if AD_PREFIX_REGEX.match(n):
        rem = AD_PREFIX_REGEX.sub('', n).strip()
        c_rem = clean_sam_project_name(rem, _allow_split=False)
        if c_rem and c_rem.lower() not in GENERIC_PROJECT_NAMES:
            return c_rem
        return ""
    if CONTACT_PHRASE_REGEX.search(n):
        return ""

    # 7. ตัด Condition suffix (เช่น ": ปรับปรุง")
    n = CONDITION_SUFFIX_REGEX.sub('', n).strip()

    # 8. ตัดเลขชั้น / อาคาร / ห้อง ในวงเล็บหรือก้ามปูท้ายชื่อ และตัด Unclosed brackets หรือคำระบุชั้น/อาคาร
    n = re.sub(r'\[\s*(?:ชั้น|fl|floor|room|ห้อง|อาคาร|ตึก|unit|tower|phase|เฟส|คอปเปอร์โซน|ทิมเบอร์โซน|โซน)[^\]]*\]', '', n, flags=re.I)
    n = re.sub(r'\(\s*(?:ชั้น|fl|floor|room|ห้อง|อาคาร|ตึก|unit|tower|phase|เฟส|คอปเปอร์โซน|ทิมเบอร์โซน|โซน)[^\)]*\)', '', n, flags=re.I)
    n = re.sub(r'\[\s*(?:ชั้น|fl|floor|room|ห้อง|อาคาร|ตึก|unit|tower|phase|เฟส|คอปเปอร์โซน|ทิมเบอร์โซน|โซน).*$', '', n, flags=re.I)
    n = re.sub(r'\(\s*(?:ชั้น|fl|floor|room|ห้อง|อาคาร|ตึก|unit|tower|phase|เฟส|คอปเปอร์โซน|ทิมเบอร์โซน|โซน).*$', '', n, flags=re.I)
    n = re.sub(r'\[[^\]]*$', '', n)
    n = re.sub(r'\([^\)]*$', '', n)
    n = re.sub(r'\[\s*\d+\s*(?:ชั้น)?\s*\]', '', n)
    n = re.sub(r'\(\s*\d+\s*(?:ชั้น)?\s*\)', '', n)
    n = re.sub(r'[\s\-_/]+(?:อาคาร|ตึก)\s+[a-zA-Z0-9ก-๙]\s+ชั้น\s*\d+.*$', '', n, flags=re.I)
    n = re.sub(r'[\s\-_/]+ชั้น\s*\d+.*$', '', n, flags=re.I)

    # 9. ตรวจสอบที่อยู่/ถนน/ซอย รั่วไหลเข้ามาในชื่อ
    if (('ตำบล' in n and 'อำเภอ' in n) or ('แขวง' in n and 'เขต' in n) or 
        re.match(r'^(?:ติดถนน|ริมถนน|ริมคลอง|เลียบคลอง|ใกล้ถนน|หน้าโรงเรียน|เชิงสะพาน|ปากซอย)\s*', n) or
        re.match(r'^(?:ถนน|ถ\.)\s*[ก-๙a-zA-Z0-9]', n) or
        re.match(r'^(?:ซอย|ซ\.)\s*[ก-๙a-zA-Z0-9]', n) or
        re.match(r'^(?:ชุมชน|ชุมชุน)\s*[ก-๙a-zA-Z0-9]', n)):
        return ""

    # 10. ตัด Bank property type prefix (เช่น "บ้านเดี่ยว 2 ชั้น โครงการบางกอก บูเลอวาร์ด" -> "บางกอก บูเลอวาร์ด")
    match_bank = BANK_DESC_PREFIX_REGEX.match(n)
    if match_bank:
        remainder = n[match_bank.end():].strip()
        if remainder and len(remainder) >= 2:
            n = remainder

    # ตัดเลขชั้นนำหน้าหากเหลืออยู่ เช่น "2 ชั้น บ้านวิสต้า วิลล์" -> "บ้านวิสต้า วิลล์"
    n = re.sub(rf'^{STOREY_REGEX}\s+', '', n, flags=re.I)

    # 11. ตัด Standalone property type prefix เช่น "ห้องชุด ไอดีโอ..." -> "ไอดีโอ..."
    match_standalone = STANDALONE_PROP_TYPE_PREFIX.match(n)
    if match_standalone:
        remainder = n[match_standalone.end():].strip()
        if remainder and len(remainder) >= 2:
            n = remainder

    # 12. ตัด Generic prefix (โครงการ, หมู่บ้าน, อาคารชุด ฯลฯ)
    if not (n.startswith('บ้านกลางเมือง') or n.startswith('บ้านกลางกรุง') or n.startswith('บ้านพฤกษา')):
        match_gen = GENERIC_PREFIX_REGEX.match(n)
        if match_gen:
            rem = n[match_gen.end():].strip()
            if rem and len(rem) >= 2:
                n = rem

    # 13. ตรวจสอบสเปกพื้นที่
    if AREA_SPEC_REGEX.search(n):
        return ""
        
    # ตัดคำโฆษณา/สเปก/ทำเลต่อท้าย (Ad Noise Stripping)
    n = clean_trailing_ad_noise(n)
    if not n or n.lower() in GENERIC_PROJECT_NAMES:
        return ""

    # 14. แยกแบรนด์ที่เขียนติดกันโดยไม่มีเว้นวรรค
    n = re.sub(r'(?i)\bไอดีโอโมบิ', 'ไอดีโอ โมบิ ', n)
    n = re.sub(r'(?i)\bลุมพินีวิลล์', 'ลุมพินี วิลล์ ', n)
    n = re.sub(r'(?i)\bลุมพินีพาร์ค', 'ลุมพินี พาร์ค ', n)
    n = re.sub(r'(?i)\bลุมพินีเพลส', 'ลุมพินี เพลส ', n)
    n = re.sub(r'(?i)\bพลัมคอนโด', 'พลัม คอนโด ', n)
    n = re.sub(r'(?i)\bเดอะเบส', 'เดอะ เบส ', n)
    n = re.sub(r'(?i)\bเดอะทรัสต์', 'เดอะ ทรัสต์ ', n)
    n = re.sub(r'(?i)\bเดอะไลน์', 'เดอะ ไลน์ ', n)
    n = re.sub(r'(?i)\bเดอะทรี', 'เดอะ ทรี ', n)
    n = re.sub(r'(?i)\bเดอะคีย์', 'เดอะ คีย์ ', n)
    n = re.sub(r'(?i)\bศุภาลัยปาร์ค', 'ศุภาลัย ปาร์ค ', n)
    n = re.sub(r'(?i)\bศุภาลัยซิตี้', 'ศุภาลัย ซิตี้ ', n)
    n = re.sub(r'(?i)\bบางกอกบูเลอวาร์ด', 'บางกอก บูเลอวาร์ด ', n)
    
    # แยกคำภาษาไทยที่ติดอยู่กับแบรนด์ เช่น "ไอดีโอ โมบิวงศ์สว่าง" -> "ไอดีโอ โมบิ วงศ์สว่าง"
    n = re.sub(r'(ไอดีโอ\s+โมบิ)([ก-๙])', r'\1 \2', n)
    n = re.sub(r'(พลัม\s+คอนโด)([ก-๙])', r'\1 \2', n)
    n = re.sub(r'(เดอะ\s+เบส)([ก-๙])', r'\1 \2', n)
    n = re.sub(r'(เดอะ\s+ทรัสต์)([ก-๙])', r'\1 \2', n)
    n = re.sub(r'(ลุมพินี\s+วิลล์)([ก-๙])', r'\1 \2', n)
    n = re.sub(r'(ลุมพินี\s+พาร์ค)([ก-๙])', r'\1 \2', n)
    n = re.sub(r'(ลุมพินี\s+เพลส)([ก-๙])', r'\1 \2', n)

    # ตัดคำนำหน้าซ้ำซ้อนเช่น LPN ลุมพินี -> ลุมพินี
    n = re.sub(r'(?i)\b(?:lpn|ลุมพินี)\s+(?=ลุมพินี)', '', n)

    # 15. แปลงแบรนด์เข้าสู่ Canonical Thai Brand (Ideo -> ไอดีโอ, Plum -> พลัม คอนโด ฯลฯ)
    for pattern, canonical_name in COMPILED_BRAND_PATTERNS:
        if pattern.search(n):
            n = pattern.sub(canonical_name, n)
            break

    # 16. แปลงชื่อทำเลภาษาอังกฤษยอดนิยมเป็นภาษาไทย (Bilingual Location Normalization)
    for loc_pattern, loc_canonical in COMPILED_LOCATION_PATTERNS:
        if loc_pattern.search(n):
            n = loc_pattern.sub(loc_canonical, n)

    # 17. จัดมาตรฐาน Phase / เฟส
    n = normalize_phase_notation(n)

    # 18. จัดมาตรฐานเครื่องหมายยัติภังค์ (Hyphen) ไม่ให้มีช่องว่างเกิน เช่น "วงศ์สว่าง - อินเตอร์เชนจ์" -> "วงศ์สว่าง-อินเตอร์เชนจ์"
    n = re.sub(r'\s*-\s*', '-', n)
    # เชื่อมยัติภังค์สำหรับคำสถานี/ชุมทางยอดนิยม เช่น "วงศ์สว่าง อินเตอร์เชนจ์" -> "วงศ์สว่าง-อินเตอร์เชนจ์"
    n = re.sub(r'([ก-๙a-zA-Z0-9])\s+(อินเตอร์เชนจ์|สเตชั่น|สเตชัน)', r'\1-\2', n)

    # 19. ตัดชื่อจังหวัดซ้ำซ้อนท้ายชื่อโครงการ (เช่น "ลุมพินี วิลล์ กรุงเทพมหานคร" -> "ลุมพินี วิลล์")
    for prov in COMMON_PROJECT_PROVINCES:
        trailing_patterns = [
            f', {prov}', f',{prov}', f' {prov}', f'({prov})', f' (จ.{prov})', f' จ.{prov}'
        ]
        for tp in trailing_patterns:
            if n.endswith(tp):
                cand = n[:-len(tp)].strip().rstrip(',')
                if len(cand) >= 2:
                    n = cand
                break

    # 20. ตรวจสอบ Storey only / Bedroom only อีกครั้งหลังตัดคำ
    if n in GENERIC_PROJECT_NAMES or n.lower() in GENERIC_PROJECT_NAMES:
        return ""
    if STOREY_ONLY_REGEX.match(n) or BEDROOM_ONLY_REGEX.match(n):
        return ""

    # วงเล็บค้างท้าย เช่น "บางแค )"
    n = re.sub(r'[\(\[\{]\s*$', '', n).strip()
    n = re.sub(r'^\s*[\)\]\}]', '', n).strip()

    # 20.5 ยุบคำซ้ำติดกัน เช่น "อภิทาวน์ อภิทาวน์" -> "อภิทาวน์"
    n = re.sub(r'([ก-๙a-zA-Z0-9]+)\s+\1(?:\s+|$)', r'\1 ', n).strip()

    # 21. จัดช่องว่างและอักขระขอบนอก
    n = re.sub(r"\s+", " ", n).strip(' :-/,(._#!–—"“”’«»[]\'')
    if n.count(')') > n.count('('):
        n = re.sub(r'\)+$', '', n).strip()
    if n.count(']') > n.count('['):
        n = re.sub(r'\]+$', '', n).strip()
    
    return n if len(n) >= 2 and n.lower() not in GENERIC_PROJECT_NAMES else ""


def clean_bam_project_name(raw_name, tambon: str = "", amphoe: str = "", province: str = "", _allow_split: bool = True) -> str:
    """
    ทำความสะอาดและจัดมาตรฐานชื่อโครงการอสังหาริมทรัพย์ของ BAM (บมจ.บริหารสินทรัพย์ กรุงเทพพาณิชย์)
    
    คุณสมบัติ:
    - สกัดชื่อโครงการจริงจากชื่อประกาศ BAM ที่มักผสมประเภททรัพย์/จำนวนชั้น เช่น
      'ทาวน์เฮ้าส์ชั้นเดียว โครงการศรุตาวิลล์ เมืองระยอง' -> 'ศรุตาวิลล์'
      '2 ชั้น ในโครงการหมู่บ้าน มนวดี' -> 'มนวดี'
      'บ้านเดี่ยวชั้นเดียว บ้านเตาปูนหล่ายต้า ลำปาง' -> 'บ้านเตาปูนหล่ายต้า'
    - ตัดข้อมูลที่เป็นเพียงทำเล/ถนน/ซอย/คำบรรยายทรัพย์ที่ไม่มีชื่อโครงการจริงออกเป็นค่าว่าง เช่น
      'ติดถนนพหลโยธิน เมืองลำปาง' -> ''
      'เมืองนนทบุรี' -> ''
      'หอพักอาศัย 2 ชั้น ลำปาง' -> ''
      '3 ชั้น ซอยบรมราชชนนี 119' -> ''
    - ตัดชื่ออำเภอ/จังหวัดที่พ่วงท้ายชื่อโครงการ เช่น
      'แลนซีโอคริป เพชรเกษม 81 กระทุ่มแบน' -> 'แลนซีโอ คริป เพชรเกษม 81'
      'บ้านสวนแสนสุข องครักษ์' -> 'บ้านสวนแสนสุข'
    - จัดกลุ่มและแมปแบรนด์เข้าสู่ Canonical Thai Brand (100+ แบรนด์)
    """
    if not raw_name or pd.isna(raw_name):
        return ""
    
    s = str(raw_name).strip()
    s = unicodedata.normalize('NFKC', s)
    s = s.replace('\u0e4d\u0e32', '\u0e33')
    s = re.sub(r'[\u0e48-\u0e4c]{2,}', lambda m: m.group(0)[0], s)
    
    if s.lower() in ['', 'nan', 'none', 'null', '-', '--', '?', '#name?', '.', '..']:
        return ""
        
    s = re.sub(r'\((?:แปลงมุม|ห้องริม|หลังริม|ห้องมุม|ขายตามสภาพ|สภาพดี|ปรับปรุงแล้ว|พร้อมอยู่|แปลงที่\s*\d+)\)', '', s, flags=re.I)
    s = re.sub(r'\((?:ชั้น|fl|floor|room|ห้อง|อาคาร|ตึก|unit)[^\)]*\)', '', s, flags=re.I)
    s = re.sub(r'\[(?:ชั้น|fl|floor|room|ห้อง|อาคาร|ตึก|unit)[^\]]*\]', '', s, flags=re.I)

    clean_strip = s.strip()
    clean_no_prefix = re.sub(r'^(?:อ\.|จ\.|ต\.|เมือง|อำเภอ|ตำบล|เขต|แขวง)\s*', '', clean_strip)
    
    all_amp = get_all_amphoes()
    if clean_strip in ALL_PROVINCES or f"จ.{clean_strip}" in ALL_PROVINCES or clean_no_prefix in ALL_PROVINCES:
        return ""
    if clean_strip in all_amp or clean_no_prefix in all_amp:
        return ""
    if amphoe and (clean_strip == amphoe.strip() or clean_no_prefix == amphoe.strip()):
        return ""
    if province and (clean_strip == province.strip() or clean_no_prefix == province.strip()):
        return ""
    if tambon and (clean_strip == tambon.strip() or clean_no_prefix == tambon.strip()):
        return ""

    for bj in BUILDING_DESC_JUNK:
        if s.startswith(bj):
            return ""

    # Priority 1: สกัดชื่อโครงการจริงหากมีคำว่า "โครงการ", "หมู่บ้าน", "มบ."
    m_proj = re.search(r'(?:ใน|ติด)?(?:โครงการหมู่บ้าน|หมู่บ้านโครงการ|โครงการ|หมู่บ้าน|โคงการ|โครการ|(?<!ก)(?<!ตร\.)(?<!ลบ\.)(?<!ซ)(?<!ช)(?:มบ\.|ม\.)(?=[ก-๙a-zA-Z])(?!(?:ใกล้|ตรงข้าม|ติด|เยื้อง|รังสิต|กรุงเทพ|ธรรมศาสตร์|เกษตร|มหิดล|ศรีนคริน|หอการค้า)))\s*([ก-๙a-zA-Z0-9\s\-_()]+)', s)
    if m_proj:
        extracted = m_proj.group(1).strip()
        if len(extracted) >= 2 and extracted not in ALL_PROVINCES and extracted not in all_amp:
            s = extracted
    else:
        # ตัดคำนำหน้าประเภททรัพย์และจำนวนชั้น
        s = re.sub(rf'^{PROP_REGEX}\s*(?:{STOREY_REGEX})?\s*', '', s, flags=re.I)
        s = re.sub(rf'^{STOREY_REGEX}\s+', '', s, flags=re.I)

    # Priority 2: ตรวจจับกรณีเป็นเพียงถนน / ซอย / ชุมชน ที่ไม่มีชื่อโครงการ
    if re.match(r'^(?:ติดถนน|ริมถนน|ริมคลอง|เลียบคลอง|ใกล้ถนน|หน้าโรงเรียน|เชิงสะพาน|ปากซอย)\s*', s):
        return ""
    if re.match(r'^(?:ถนน|ถ\.)\s*[ก-๙a-zA-Z0-9]', s):
        return ""
    if re.match(r'^(?:ซอย|ซ\.)\s*[ก-๙a-zA-Z0-9]', s):
        return ""
    if re.match(r'^(?:ชุมชน|ชุมชุน)\s*[ก-๙a-zA-Z0-9]', s):
        return ""

    words = s.split()
    if len(words) <= 3:
        if all(w in ALL_PROVINCES or w in all_amp or re.match(rf'^{PROP_REGEX}$', w) or re.match(rf'^{STOREY_REGEX}$', w) for w in words):
            return ""

    if re.match(rf'^{PROP_REGEX}\s*(?:{STOREY_REGEX})?$', s) or re.match(rf'^{STOREY_REGEX}$', s):
        return ""

    # Priority 3: ตัดชื่ออำเภอ/จังหวัดที่พ่วงท้ายชื่อโครงการ
    for p_cand in [province, amphoe] + ALL_PROVINCES:
        if not p_cand: continue
        p_cand = re.sub(r'^(?:อ\.|จ\.|จังหวัด|อำเภอ)\s*', '', p_cand.strip()).strip()
        if not p_cand: continue
        pat = rf'[\s,/]+(?:(?:อ\.|จ\.|จังหวัด|อำเภอ|เขต|เมือง)\s*)*{re.escape(p_cand)}$'
        sub_cand = re.sub(pat, '', s).strip()
        sub_cand = re.sub(r'[\s,/]+(?:อ\.?|จ\.?)$', '', sub_cand).strip()
        if len(sub_cand) >= 3 and sub_cand not in ALL_PROVINCES and sub_cand not in all_amp and not re.match(rf'^{PROP_REGEX}$', sub_cand):
            s = sub_cand

    s = re.sub(rf'^{PROP_REGEX}\s*', '', s)
    s = re.sub(r'^(?:โครงการ|หมู่บ้าน|โคงการ|โครการ)\s*', '', s)
    
    # ส่งต่อเข้าสู่ Standard Normalization (Brand Harmonization)
    res = clean_sam_project_name(s, _allow_split=_allow_split)
    
    if not res or len(res) <= 1:
        return ""
    if res in ALL_PROVINCES or res in all_amp or res in [f"เมือง{p}" for p in ALL_PROVINCES]:
        return ""
    if amphoe and res == amphoe.strip():
        return ""
    if tambon and res == tambon.strip():
        return ""
    if re.match(rf'^{PROP_REGEX}$', res) or re.match(rf'^{STOREY_REGEX}$', res):
        return ""
    if re.match(r'^(?:ติดถนน|ริมถนน|ริมคลอง|เลียบคลอง|ปากซอย)\s*', res):
        return ""
    if re.match(r'^(?:ถนน|ถ\.|ซอย|ซ\.)\s*', res):
        return ""
        
    return res



_CANONICAL_LOCK = threading.Lock()
_CANONICAL_MAP = None

def get_canonical_map() -> dict:
    """
    โหลดตาราง Mapping แปลงคำเพี้ยน/การเว้นวรรค/การสะกดต่างกันให้กลายเป็นชื่อทางการมาตรฐานเดียวกัน
    """
    global _CANONICAL_MAP
    if _CANONICAL_MAP is not None:
        return _CANONICAL_MAP
    with _CANONICAL_LOCK:
        if _CANONICAL_MAP is not None:
            return _CANONICAL_MAP
        mapping = {}
        try:
            import json
            candidates = []
            if getattr(sys, '_MEIPASS', None):
                candidates.append(os.path.join(sys._MEIPASS, "project_canonical_mapping.json"))
            base_dir = os.path.dirname(os.path.abspath(__file__))
            candidates.append(os.path.join(base_dir, "project_canonical_mapping.json"))
            candidates.append(os.path.join(base_dir, "..", "data", "project_canonical_mapping.json"))
            candidates.append(os.path.join(base_dir, "data", "project_canonical_mapping.json"))
            p = next((x for x in candidates if os.path.exists(x)), None)
            if p:
                with open(p, "r", encoding="utf-8") as f:
                    mapping = json.load(f)
        except Exception:
            pass
        _CANONICAL_MAP = mapping
        return _CANONICAL_MAP

_BRAND_OUTPUT_NAMES = frozenset(rep for _, rep in BRAND_REPLACEMENTS)

def _collapse_duplicate_words(s: str) -> str:
    """Collapse consecutive repeated tokens and strip outer noise punctuation."""
    s = re.sub(r'([ก-๙a-zA-Z0-9]+)\s+\1(?:\s+|$)', r'\1 ', str(s))
    return s.strip(' “"\'’‘”«»-–—:,./()[]')

def clean_project_name(raw_name, tambon: str = "", amphoe: str = "", province: str = "", company: str = "", _allow_split: bool = True) -> str:
    """
    ฟังก์ชันกลาง (Unified Master Function) สำหรับ Clean ชื่อโครงการของทุกค่าย (BAM, SAM, LED และอื่นๆ)
    """
    comp = str(company or "").strip().upper()
    if comp == "BAM":
        cln = clean_bam_project_name(raw_name, tambon=tambon, amphoe=amphoe, province=province, _allow_split=_allow_split)
    else:
        cln = clean_sam_project_name(raw_name, _allow_split=_allow_split)
    canon_map = get_canonical_map()
    if cln and cln in canon_map:
        return canon_map[cln]

    if cln and (amphoe or province):
        if province:
            pv = str(province).strip().replace("จ.", "").replace("จังหวัด", "").strip()
            if pv and pv not in ["เลย", "แพร่", "น่าน"]:
                cln = re.sub(rf'[\s\-_/,]+(?:จ\.|จังหวัด)?\s*{re.escape(pv)}\s*$', '', cln).strip()
        if amphoe:
            ap = str(amphoe).strip().replace("อ.", "").replace("อำเภอ", "").replace("เขต", "").strip()
            if ap and ap not in ["คง", "ปง", "พล", "เมือง"]:
                # Unconditionally strip explicit admin prefixes / delimiters / เมืองX suffixes
                cand_explicit = re.sub(rf'(?:[\s\-_]*[,/][\s\-_]*|[\s\-_]+(?:อ\.|อำเภอ|เขต)\s*){re.escape(ap)}\s*$', '', cln).strip()
                if cand_explicit != cln and cand_explicit not in _BRAND_OUTPUT_NAMES:
                    cln = cand_explicit
                elif ap.startswith("เมือง"):
                    cand_city = re.sub(rf'[\s\-_]+{re.escape(ap)}\s*$', '', cln).strip()
                    if len(cand_city) >= 3 and cand_city not in _BRAND_OUTPUT_NAMES:
                        cln = cand_city
                elif comp in ("BAM", "SAM", "LED", "LED LEGAL", "GSB", "GHB", "KTB", "SCB", "KBANK", "CHAYO555"):
                    # Only strip bare trailing amphoe for bank/gov/AMC titles if remainder isn't a bare generic/brand stem
                    cand_bare = re.sub(rf'[\s\-_]+{re.escape(ap)}\s*$', '', cln).strip()
                    if len(cand_bare) >= 3 and cand_bare not in _BRAND_OUTPUT_NAMES and cand_bare.lower() not in GENERIC_PROJECT_NAMES:
                        cln = cand_bare

    if cln:
        cln_l = cln.lower().strip()
        if cln_l in ALL_PROVINCES or f"จ.{cln_l}" in ALL_PROVINCES:
            return ""
        all_amp = get_all_amphoes()
        if cln_l in all_amp or re.sub(r'^(?:เมือง|อำเภอ|เขต)\s*', '', cln_l) in all_amp:
            return ""
        if province and cln_l == province.strip().replace("จ.", "").replace("จังหวัด", "").strip().lower():
            return ""
        if amphoe and cln_l == amphoe.strip().replace("อ.", "").replace("อำเภอ", "").replace("เขต", "").strip().lower():
            return ""
        if tambon and cln_l == tambon.strip().replace("ต.", "").replace("ตำบล", "").replace("แขวง", "").strip().lower():
            return ""
        if cln_l in GENERIC_PROJECT_NAMES:
            return ""

        if cln in canon_map:
            cln = canon_map[cln]

    return cln


_STRICT_THAI_KEYWORDS = (
    r'(?:คอนโดมิเนียม|คอนโด|วิลล์|พาร์ค|การ์เด้น|การ์เดน|เรสซิเดนซ์|เรสซิเด้นซ์|'
    r'เพลส|ซิตี้|เอสเตท|ไฮทส์|ฮิลล์|ริเวอร์ไซด์|คอร์ท|อเวนิว|สเตชั่น|สวีท|'
    r'แมนชั่น|ลิฟวิ่ง|พาวิลเลียน|ไพรเวท)(?=$|[\s,\.\-_/()\[\]"\'ก-๙])'
)
_STRICT_EN_KEYWORDS = (
    r'\b(?:condominium|condo|ville|park|garden|residence|residences|place|city|'
    r'estate|heights|hills|hill|riverside|court|avenue|station|suites|suite|'
    r'mansion|living|pavilion|private)\b'
)
STRICT_PROJECT_KEYWORDS = rf'(?:{_STRICT_THAI_KEYWORDS}|{_STRICT_EN_KEYWORDS})'

ASSET_CODE_PATTERN = re.compile(r'^(?:[0-9]+[a-zA-Z]+|[a-zA-Z]+[0-9]+|[0-9]{4,}|[a-zA-Z]{1,4}\s*[-–—/]?\s*[0-9]+)$')

def is_valid_extracted_project(name: str, tambon: str = "", amphoe: str = "", province: str = "") -> bool:
    if not name or len(name) < 2:
        return False
    name = name.strip(' “"\'’‘”«»-–—:,./()[]')
    if len(name) < 2:
        return False
    nl = name.lower().strip()
    if nl in GENERIC_PROJECT_NAMES:
        return False
    if nl in ALL_PROVINCES or f"จ.{nl}" in ALL_PROVINCES:
        return False
    all_amp = get_all_amphoes()
    if nl in all_amp or re.sub(r'^(?:เมือง|อำเภอ|เขต)\s*', '', nl) in all_amp:
        return False
    if province and nl == province.strip().replace("จ.", "").replace("จังหวัด", "").strip().lower():
        return False
    if amphoe and nl == amphoe.strip().replace("อ.", "").replace("อำเภอ", "").replace("เขต", "").strip().lower():
        return False
    if tambon and nl == tambon.strip().replace("ต.", "").replace("ตำบล", "").replace("แขวง", "").strip().lower():
        return False
    if re.search(r'(?:เซ็นทรัล|central|เดอะมอลล์|the\s*mall|โลตัส|lotus|บิ๊กซี|big\s*c|โรบินสัน|robinson)', nl, re.I):
        return False
    if 'ใกล้' in nl or 'ตรงข้าม' in nl or 'เยื้อง' in nl or re.search(r'^(?:ติดถนน|ติด\s*(?:mrt|bts|ถนน|ทะเล|หาด|ทางด่วน))', nl):
        return False
    if re.match(r'^[\d\s\-_/.,()]+$', name):
        return False
    if ASSET_CODE_PATTERN.match(name.replace(" ", "")):
        return False
    return True

def extract_project_from_title(title: str, tambon: str = "", amphoe: str = "", province: str = "", company: str = "") -> str:
    """
    สกัดและทำความสะอาดชื่อโครงการจากชื่อประกาศ (Listing Title)
    รองรับทุกค่าย (Livinginsider, DDproperty, Baania, ZmyHome, NaYoo, Bank Portals)
    """
    if not title or pd.isna(title):
        return ""
    t = str(title).strip()
    t = unicodedata.normalize('NFKC', t).replace('\u0e4d\u0e32', '\u0e33')
    t = t.strip(' “"\'’‘”«»-–—:,./')

    # Case 0: Portals with structured "Title : Subtitle, Province" e.g. DDproperty
    if ":" in t:
        parts = [p.strip() for p in t.split(":") if p.strip()]
        if len(parts) >= 2:
            if not any(parts[1].startswith(c) for c in ['ปรับปรุง', 'สภาพดี', 'พร้อมอยู่', 'สร้างเอง', 'ขายด่วน']):
                cln_full = clean_project_name(t, tambon=tambon, amphoe=amphoe, province=province, company=company)
                if is_valid_extracted_project(cln_full, tambon, amphoe, province):
                    res = _collapse_duplicate_words(cln_full)
                    if is_valid_extracted_project(res, tambon, amphoe, province):
                        return res

    # 1. Look for parentheses / quotes containing project candidates
    matches_paren = list(re.finditer(r'[\(\[\{“"\'‘]([^\)\]\}”"\'’]+)[\)\]\}”"\'’]', t))
    for m in matches_paren:
        inner = m.group(1).strip()
        if ASSET_CODE_PATTERN.match(inner.replace(" ", "")) or re.search(r'^(?:ชั้น|fl|room|ห้อง|แปลงมุม|ราคา|สภาพ|สร้างเอง|เนื้อที่|\d+)', inner, re.I):
            continue
            
        has_kw = bool(re.search(STRICT_PROJECT_KEYWORDS, inner, re.I))
        has_br = any(p.search(inner) for p, _ in COMPILED_BRAND_PATTERNS)
        if has_kw or has_br:
            cln_inner = clean_project_name(inner, tambon=tambon, amphoe=amphoe, province=province, company=company)
            if is_valid_extracted_project(cln_inner, tambon, amphoe, province):
                res = _collapse_duplicate_words(cln_inner)
                if is_valid_extracted_project(res, tambon, amphoe, province):
                    return res
        
        # If inner is English project name e.g. (Pla Beach Town), look for Thai project right before
        if re.match(r'^[a-zA-Z0-9\s\-_.]+$', inner) and len(inner) >= 4 and not ASSET_CODE_PATTERN.match(inner.replace(" ", "")):
            pre_text = t[:m.start()].strip()
            m_pre = re.search(r'([ก-๙0-9\s\-_]+)$', pre_text)
            if m_pre:
                cand_pre = clean_trailing_ad_noise(m_pre.group(1).strip())
                cand_pre = re.sub(r'^(?:ขาย|ให้เช่า|เช่า|ขายด่วน|ขายด่วนมาก|ด่วน|สำหรับขาย)\s*', '', cand_pre, flags=re.I)
                cand_pre = re.sub(r'^(?:บ้านเดี่ยว|บ้านแฝด|ทาวน์โฮม|ทาวน์เฮ้าส์|คอนโด|คอนโดมิเนียม|ห้องชุด|อาคารพาณิชย์|ตึกแถว|ที่ดิน)(?:\s*\d*\s*ชั้น)?\s*', '', cand_pre, flags=re.I)
                cand_pre = re.sub(r'^(?:\d+\s*(?:ห้องนอน|ห้องน้ำ|นอน|น้ำ|ห้อง|ชั้น|ตร\.?ว|ตร\.?ม|ตารางวา|ไร่|งาน)|ชั้น\s*\d+)\s*', '', cand_pre, flags=re.I)
                cand_pre = cand_pre.strip()
                cln_pre = clean_project_name(cand_pre, tambon=tambon, amphoe=amphoe, province=province, company=company)
                if is_valid_extracted_project(cln_pre, tambon, amphoe, province):
                    res = _collapse_duplicate_words(cln_pre)
                    if is_valid_extracted_project(res, tambon, amphoe, province):
                        return res

    # 2. Rule 1: Explicit "โครงการ", "หมู่บ้าน", "มบ."
    m_proj = re.search(
        r'(?:^|[^\d\s/]|(?<=\d)\s*|\s+)(?:ใน|ติด)?(?:โครงการหมู่บ้าน|หมู่บ้านโครงการ|ในโครงการ|โครงการ|หมู่บ้าน|'
        r'(?<!ก)(?<!ตร\.)(?<!ลบ\.)(?<!ซ)(?<!ช)(?:มบ\.|ม\.)(?=[ก-๙a-zA-Z])(?!(?:ใกล้|ตรงข้าม|ติด|เยื้อง|รังสิต|กรุงเทพ|ธรรมศาสตร์|เกษตร|มหิดล|ศรีนคริน|หอการค้า))|'
        r'(?<!/)(?<!คอนโดมิเนียม/)อาคารชุด)\s*([ก-๙a-zA-Z0-9\s\-_()]+)',
        t
    )
    if m_proj:
        cand = m_proj.group(1).strip()
        cand = clean_trailing_ad_noise(cand)
        cln = clean_project_name(cand, tambon=tambon, amphoe=amphoe, province=province, company=company)
        if is_valid_extracted_project(cln, tambon, amphoe, province):
            res = _collapse_duplicate_words(cln)
            if is_valid_extracted_project(res, tambon, amphoe, province):
                return res

    # 3. Rule 2: Brand patterns
    for pat, brand_name in COMPILED_BRAND_PATTERNS:
        m_b = pat.search(t)
        if m_b:
            prefix = t[:m_b.start()].rstrip()
            if re.search(r'(?:ซอย|ซ\.|ถนน|ถ\.|แยก|สะพาน|คลอง)$', prefix):
                continue
            cand = t[m_b.start():].strip()
            cand = clean_trailing_ad_noise(cand)
            cln = clean_project_name(cand, tambon=tambon, amphoe=amphoe, province=province, company=company)
            if is_valid_extracted_project(cln, tambon, amphoe, province):
                res = _collapse_duplicate_words(cln)
                if is_valid_extracted_project(res, tambon, amphoe, province):
                    return res

    # 4. Rule 3: Strict Project Keyword Search (คอนโด, วิลล์, พาร์ค, การ์เด้น, ซิตี้, เรสซิเดนซ์, ฯลฯ)
    m_kw = re.search(rf'([ก-๙a-zA-Z0-9\s\-_]{{2,30}}?{STRICT_PROJECT_KEYWORDS}[ก-๙a-zA-Z0-9\s\-_]*)', t, re.I)
    if m_kw:
        cand = m_kw.group(1).strip()
        cand = re.sub(r'^(?:ขาย|ให้เช่า|เช่า|ขายด่วน|ขายด่วนมาก|ด่วน|สำหรับขาย)\s*', '', cand, flags=re.I)
        cand = re.sub(r'^(?:บ้านเดี่ยว|บ้านแฝด|ทาวน์โฮม|ทาวน์เฮ้าส์|คอนโด|คอนโดมิเนียม|ห้องชุด|อาคารพาณิชย์|ตึกแถว|ที่ดิน|บ้าน)(?:\s*\d*\s*ชั้น)?\s*', '', cand, flags=re.I)
        cand = re.sub(r'^(?:\d+\s*(?:ห้องนอน|ห้องน้ำ|นอน|น้ำ|ห้อง|ชั้น|ตร\.?ว|ตร\.?ม|ตารางวา|ไร่|งาน)|ชั้น\s*\d+)\s*', '', cand, flags=re.I)
        cand = re.sub(r'^(?:(?:เพียง|ราคา)\s*[\d,.]+(?:\s*(?:ล้านบาท|ล้าน|แสน|บาท|.-))?|[\d,.]+\s*(?:ล้านบาท|ล้าน|แสน|บาท|.-))(?:เท่านั้น)?\s*', '', cand, flags=re.I)
        cand = clean_trailing_ad_noise(cand)
        cln = clean_project_name(cand, tambon=tambon, amphoe=amphoe, province=province, company=company)
        if is_valid_extracted_project(cln, tambon, amphoe, province):
            res = _collapse_duplicate_words(cln)
            if is_valid_extracted_project(res, tambon, amphoe, province):
                return res

    return ""

def is_same_project(name1: str, name2: str, threshold: float = 0.85) -> bool:
    """
    ตรวจสอบว่าชื่อโครงการ 2 ชื่อ หมายถึงโครงการเดียวกันหรือไม่ (Fuzzy & Token Match)
    รองรับกรณีสลับคำ เช่น 'ไอดีโอ โมบิ สุขุมวิท 66' กับ 'Ideo Mobi Sukhumvit 66'
    """
    if not name1 or not name2:
        return False
    
    c1 = clean_project_name(name1)
    c2 = clean_project_name(name2)
    
    if not c1 or not c2:
        return False
    if c1 == c2:
        return True
        
    compact1 = re.sub(r'[\s\-_/.]+', '', c1.lower())
    compact2 = re.sub(r'[\s\-_/.]+', '', c2.lower())
    if compact1 == compact2:
        return True
        
    tokens1 = set(c1.lower().split())
    tokens2 = set(c2.lower().split())
    if tokens1 and tokens2:
        intersection = len(tokens1.intersection(tokens2))
        union = len(tokens1.union(tokens2))
        if union > 0 and (intersection / union) >= threshold:
            return True
            
    return False

# ==============================================================================
# 4. CLI & BATCH PROCESSING (ระบบรัน Clean ไฟล์ CSV)
# ==============================================================================

def clean_csv_project_names(csv_path: str, backup: bool = True, inplace: bool = True, output_path: str = None) -> dict:
    """
    โหลดไฟล์ CSV และทำความสะอาดคอลัมน์ 'ชื่อโครงการ'
    1. ทำความสะอาดชื่อโครงการเดิมด้วย clean_project_name
    2. หากชื่อโครงการว่าง (หรือ Clean แล้วเป็นค่าว่าง) ให้ดึงชื่อโครงการจาก 'ชื่อประกาศ' ด้วย extract_project_from_title
    3. บันทึกผลลัพธ์พร้อมสำรองไฟล์เดิม .bak
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"ไม่พบไฟล์: {csv_path}")

    print(f"📖 กำลังโหลดข้อมูลจาก {csv_path} ...", flush=True)
    df = pd.read_csv(csv_path, encoding='utf-8-sig', dtype=str).fillna('')
    
    if 'ชื่อโครงการ' not in df.columns:
        raise ValueError(f"ไม่พบคอลัมน์ 'ชื่อโครงการ' ในไฟล์ {csv_path}")

    total_rows = len(df)
    original_projects = df['ชื่อโครงการ'].tolist()
    has_title = 'ชื่อประกาศ' in df.columns
    is_bam_file = 'bam' in os.path.basename(csv_path).lower()

    clean_cache = {}
    title_cache = {}

    cleaned_projects = []
    recovered_from_title_count = 0
    cleaned_existing_count = 0

    print(f"⚡ กำลังประมวลผล Clean และดึงชื่อโครงการ {total_rows:,} แถว ...", flush=True)

    tb_col = df['ตำบล'].tolist() if 'ตำบล' in df.columns else [''] * total_rows
    ap_col = df['อำเภอ'].tolist() if 'อำเภอ' in df.columns else [''] * total_rows
    pv_col = df['จังหวัด'].tolist() if 'จังหวัด' in df.columns else [''] * total_rows
    cp_col = df['บริษัท'].tolist() if 'บริษัท' in df.columns else ['BAM' if is_bam_file else ''] * total_rows
    title_col = df['ชื่อประกาศ'].tolist() if has_title else [''] * total_rows

    for orig_raw, tb_raw, ap_raw, pv_raw, cp_raw, title_raw in zip(original_projects, tb_col, ap_col, pv_col, cp_col, title_col):
        orig = str(orig_raw).strip()
        tb = str(tb_raw).strip()
        ap = str(ap_raw).strip()
        pv = str(pv_raw).strip()
        cp = str(cp_raw).strip()
        title = str(title_raw).strip() if has_title else ''

        cln = ""
        if orig:
            key = (orig, tb, ap, pv, cp)
            if key not in clean_cache:
                clean_cache[key] = clean_project_name(orig, tambon=tb, amphoe=ap, province=pv, company=cp)
            cln = clean_cache[key]
            if cln != orig:
                cleaned_existing_count += 1

        # Fallback to title extraction if project is empty or junk
        if not cln and title:
            t_key = (title, tb, ap, pv, cp)
            if t_key not in title_cache:
                title_cache[t_key] = extract_project_from_title(title, tambon=tb, amphoe=ap, province=pv, company=cp)
            ext = title_cache[t_key]
            if ext:
                cln = ext
                recovered_from_title_count += 1

        cleaned_projects.append(cln)

    non_empty_before = sum(1 for p in original_projects if p.strip())
    non_empty_after = sum(1 for p in cleaned_projects if p.strip())
    changed_count = sum(1 for b, a in zip(original_projects, cleaned_projects) if b.strip() != a.strip())
    unique_before = len(set(p for p in original_projects if p.strip()))
    unique_after = len(set(p for p in cleaned_projects if p.strip()))

    print("=" * 60, flush=True)
    print("📊 สถิติการทำความสะอาดชื่อโครงการ (Project Name Cleaning Stats):", flush=True)
    print(f"  - ไฟล์: {os.path.basename(csv_path)}", flush=True)
    print(f"  - จำนวนรายการทั้งหมด: {total_rows:,} แถว", flush=True)
    print(f"  - รายการที่มีชื่อโครงการเดิม: {non_empty_before:,} แถว", flush=True)
    print(f"  - รายการที่มีชื่อโครงการหลัง Clean: {non_empty_after:,} แถว", flush=True)
    print(f"  - ดึงชื่อโครงการจาก 'ชื่อประกาศ' ได้เพิ่ม: {recovered_from_title_count:,} รายการ", flush=True)
    print(f"  - รายการที่ได้รับการปรับปรุง/แก้ไข: {changed_count:,} แถว", flush=True)
    print(f"  - จำนวนโครงการที่ไม่ซ้ำ (Unique Projects):", flush=True)
    print(f"      เดิม: {unique_before:,} โครงการ -> หลัง Clean: {unique_after:,} โครงการ", flush=True)
    print("=" * 60, flush=True)

    sample_changes = []
    for b, a in zip(original_projects, cleaned_projects):
        if a.strip() and b.strip() != a.strip() and len(sample_changes) < 10:
            sample_changes.append((b if b.strip() else '(ว่าง)', a))
            
    if sample_changes:
        print("💡 ตัวอย่างชื่อโครงการที่ได้รับการปรับปรุงเป็นชื่อมาตรฐาน:", flush=True)
        for orig, cln in sample_changes:
            print(f"   [เดิม] {orig}  ===>  [มาตรฐาน] {cln}", flush=True)
        print("=" * 60, flush=True)

    if inplace:
        if backup:
            bak_path = csv_path + ".bak"
            if not os.path.exists(bak_path):
                import shutil
                shutil.copy2(csv_path, bak_path)
                print(f"💾 สำรองไฟล์เดิมไว้ที่: {bak_path}", flush=True)
        
        df['ชื่อโครงการ'] = cleaned_projects
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"✅ บันทึกทับไฟล์เดิมเรียบร้อยแล้ว: {csv_path}", flush=True)
    elif output_path:
        df['ชื่อโครงการ_มาตรฐาน'] = cleaned_projects
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"✅ บันทึกไฟล์ผลลัพธ์ใหม่เรียบร้อยแล้ว: {output_path}", flush=True)

    return {
        'total_rows': total_rows,
        'unique_before': unique_before,
        'unique_after': unique_after,
        'changed_count': changed_count,
        'recovered_from_title': recovered_from_title_count
    }

def main():
    parser = argparse.ArgumentParser(description="Clean and standardize Thai real estate project names.")
    parser.add_argument('--input', type=str, default="", help="Path to input CSV file")
    parser.add_argument('--output', type=str, default="", help="Path to output CSV file")
    parser.add_argument('--inplace', action='store_true', default=True, help="Update file inplace")
    parser.add_argument('--no-backup', action='store_true', help="Disable automatic .bak creation")
    args = parser.parse_args()

    input_file = args.input
    if not input_file:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(base_dir) if os.path.basename(base_dir).lower() == "py scraper" else base_dir
        sam_candidates = [
            os.path.join(root_dir, "CSV_Output", "2026_09", "SAM_NPA_New_2026_09.csv"),
            os.path.join(root_dir, "CSV_Output", "SAM_NPA_New_2026_09.csv"),
        ]
        for cand in sam_candidates:
            if os.path.exists(cand):
                input_file = cand
                break

    if not input_file or not os.path.exists(input_file):
        print(f"⚠️ กรุณาระบุไฟล์ CSV ที่ต้องการ Clean ด้วย --input <ไฟล์.csv>")
        sys.exit(1)

    clean_csv_project_names(
        csv_path=input_file,
        backup=not args.no_backup,
        inplace=args.inplace if not args.output else False,
        output_path=args.output
    )

if __name__ == "__main__":
    main()
