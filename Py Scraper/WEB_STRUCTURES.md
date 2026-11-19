# 📚 บันทึกโครงสร้างและสถาปัตยกรรมการดึงข้อมูล (Web Scraper Architecture & Data Schema Reference)

เอกสารฉบับนี้รวบรวม **โครงสร้างเว็บ (Web Structure), Endpoint, Data Schema, และเทคนิคการดึงข้อมูล** ของทุกค่ายอสังหาริมทรัพย์และ NPA ทั้งหมด **14 แหล่ง** ที่ใช้งานในระบบ All Asset Dashboard พร้อมมาตรฐานการทำความสะอาดข้อมูล (Data Cleaning) และการผสานข้อมูล (Merge Pipeline)

---

## 📋 มาตรฐานข้อมูลกลาง (Unified Master Schema: 29 Columns)

ทุกสคริปต์สแครปเปอร์จะแปลงและจัดเรียงข้อมูลให้อยู่ในโครงสร้างมาตรฐานเดียวกันก่อนบันทึกเป็น CSV โดยมีระบบไฟล์รวมกลาง [`merge_csv_monthly.py`](merge_csv_monthly.py) เป็นผู้ดูแลโครงสร้าง Master รวม **29 คอลัมน์**:

| # | ชื่อคอลัมน์ | ชนิดข้อมูล | คำอธิบาย & กฎการแปลง | ค่ายที่รองรับข้อมูลฟิลด์นี้ |
|---|---|---|---|---|
| 1 | **บริษัท** | Text | ชื่อค่าย: `LED`, `LED_SOLD`, `SAM`, `BAM`, `Chayo555`, `GHB`, `KBANK`, `KTB`, `SCB`, `GSB`, `DDproperty`, `Livinginsider`, `NaYoo`, `ZmyHome`, `Baania` | ทุกค่าย (14+1 ค่าย) |
| 2 | **ID** | Text | Primary Key ไม่ซ้ำกันในระบบของค่ายนั้นๆ | ทุกค่าย (14 ค่าย) |
| 3 | **รหัสทรัพย์** | Text | รหัสอ้างอิงทรัพย์ (Property Code) หากไม่มีให้ใช้ `ID` แทน | ทุกค่าย (14 ค่าย) |
| 4 | **ชื่อโครงการ** | Text | ชื่อหมู่บ้าน/คอนโด/โครงการ (ผ่านการทำความสะอาดชื่อโครงการ) | ทุกค่าย (14 ค่าย) |
| 5 | **ประเภททรัพย์** | Text | แปลงเป็นหมวดมาตรฐาน (บ้านเดี่ยว, ห้องชุดพักอาศัย, ทาวน์เฮ้าส์, ที่ดินเปล่า, อาคารพาณิชย์, โรงงาน/โกดัง, โรงแรม/รีสอร์ท, อพาร์ทเมนท์, อาคารสำนักงาน, บ้านแฝด) | ทุกค่าย (14 ค่าย) |
| 6 | **ประเภทการขาย** | Text | `ขาย`, `ทรัพย์ธนาคาร`, `ขายทอดตลาด (ปลอดจำนอง)`, `ขายทอดตลาด (จำนองติดไป)` (ตัด NPL และให้เช่าออก) | ทุกค่าย (14 ค่าย) |
| 7 | **ราคา** | Numeric (Float) | ราคาขาย/ราคาประเมิน (บาท) ห้ามมีคอมม่า, กรองราคา < 500 บาทออก และคลี่ตัวเลขติดกัน (Glued Range) | ทุกค่าย (14 ค่าย) |
| 8 | **ตำบล** | Text | ตำบล/แขวง (ตัดคำนำหน้า 'ต.', 'แขวง' และตัดวงเล็บสาขาออก ไม่ให้มีตัวอักษรภาษาอังกฤษ) | ทุกค่าย (14 ค่าย) |
| 9 | **อำเภอ** | Text | อำเภอ/เขต (ตัดคำนำหน้า 'อ.', 'เขต' และแก้ปัญหาคำว่า 'เมือง' โดดๆ ให้ระบุจังหวัดต่อท้าย เช่น 'เมืองชลบุรี') | ทุกค่าย (14 ค่าย) |
| 10 | **จังหวัด** | Text | ชื่อจังหวัดมาตรฐาน 77 จังหวัด (เช่น `กรุงเทพมหานคร`, `พระนครศรีอยุธยา`, `ชลบุรี`) | ทุกค่าย (14 ค่าย) |
| 11 | **ละติจูด** | Numeric (Float) | พิกัด WGS84 Latitude (ทศนิยม 4-6 ตำแหน่ง) | ทุกค่าย (14 ค่าย) |
| 12 | **ลองจิจูด** | Numeric (Float) | พิกัด WGS84 Longitude (ทศนิยม 4-6 ตำแหน่ง) | ทุกค่าย (14 ค่าย) |
| 13 | **ชื่อประกาศ** | Text | หัวข้อประกาศ หรือสร้างจาก `ประเภท + โครงการ + ตำบล อำเภอ จังหวัด` | ทุกค่าย (14 ค่าย) |
| 14 | **ลิงก์** | Text | URL หน้าประกาศตรงของทรัพย์ หรือ Bridge URL สำหรับค้นหาต่อ | ทุกค่าย (14 ค่าย) |
| 15 | **เนื้อที่ (ตร.ว.)** | Text | รูปแบบ `ไร่-งาน-ตร.ว.` เช่น `1-2-50`, `0-0-25.5` | ทุกค่าย (14 ค่าย) |
| 16 | **พื้นที่ใช้สอย (ตร.ม.)** | Numeric (Float) | ขนาดพื้นที่ใช้สอยตัวอาคาร/ห้องชุด | ทุกค่าย (14 ค่าย) |
| 17 | **วันที่ดึงข้อมูล** | Datetime | รูปแบบ `YYYY-MM-DD` หรือ `YYYY-MM-DD HH:MM:SS` | ทุกค่าย (14 ค่าย) |
| 18 | **ห้องนอน** | Numeric (Int) | จำนวนห้องนอน (0 = สตูดิโอ) | ทุกค่าย (ถ้ามี) |
| 19 | **ห้องน้ำ** | Numeric (Int) | จำนวนห้องน้ำ | ทุกค่าย (ถ้ามี) |
| 20 | **ที่จอดรถ** | Numeric (Int) | จำนวนที่จอดรถ | ทุกค่าย (ถ้ามี) |
| 21 | **ชั้น** | Text | ชั้นของยูนิตห้องชุด (เช่น `12`, `12A`, `G`) หรือจำนวนชั้นของอาคาร (เช่น `2 ชั้น`, `3.5 ชั้น`) | **ทุกค่าย (14 ค่าย)** |
| 22 | **วันประกาศ** | Text/Date | วันที่ลงประกาศ หรือวันที่อัปเดตข้อมูลล่าสุด | ทุกค่าย (ถ้ามี) |
| 23 | **เลขโฉนด** | Text | เลขที่โฉนดที่ดิน สำหรับเชื่อมต่อระบบ LandsMaps เพื่อดึงพิกัดแปลงจริง | `GSB`, `LED`, `LED_SOLD`, `NaYoo` |
| 24 | **โจทก์** | Text | ชื่อโจทก์ผู้ฟ้องบังคับคดี | `LED`, `LED_SOLD` |
| 25 | **ศาล** | Text | ชื่อศาลเจ้าของสำนวนคดี | `LED`, `LED_SOLD` |
| 26 | **ยอดเข้าชม** | Numeric (Int) | สถิติจำนวนครั้งที่มีผู้เปิดเข้าชมประกาศ | `KTB`, `Livinginsider`, `NaYoo`, `ZmyHome` |
| 27 | **ยอดคลิก** | Numeric (Int) | สถิติจำนวนครั้งที่มีผู้คลิกดูทรัพย์ | `Livinginsider` |
| 28 | **ราคาขายได้** | Numeric (Float) | ราคาจบประมูลที่ขายทอดตลาดได้จริง (บาท) | `LED_SOLD` |
| 29 | **วันที่ขาย** | Text/Date | วันที่ขายทอดตลาดสำเร็จ | `LED_SOLD` |

---

## 🗺️ โมดูลมาตรฐานและเอนจินการทำความสะอาดข้อมูล (Core Utility Engines)

### 1. โมดูลจัดการที่อยู่และ GIS ([`clean_location_util.py`](clean_location_util.py))
ทำงานร่วมกับฐานข้อมูลเวกเตอร์ขอบเขตการปกครองประเทศไทย:
- [`subdistricts.geojson`](subdistricts.geojson) (ขอบเขตระดับตำบล/แขวง)
- [`districts.geojson`](districts.geojson) (ขอบเขตระดับอำเภอ/เขต)

* **Reverse Geocoding (Offline STRtree Point-in-Polygon)**:
  - แปลงพิกัด ละติจูด/ลองจิจูด เป็น ตำบล/อำเภอ/จังหวัด ในหน่วยความจำ RAM ความเร็วสูง (<0.1ms/จุด)
* **Forward Geocoding / Centroid Imputation**:
  - สำหรับทรัพย์ที่มีชื่อที่อยู่ชัดเจนแต่ไม่มีพิกัด ระบบจะดึงพิกัดจุดกึ่งกลาง (Centroid) ของตำบล/อำเภอนั้นจาก `subdistricts.geojson` มาเติมให้อัตโนมัติ
* **Smart Text Normalization & Comprehensive Location Repair**:
  - **ฟื้นฟูชื่ออำเภอที่ถูกตัดท้าย (Truncated Districts)**: แก้ไขชื่ออำเภอจากระบบราชการ (LED, GHB, GSB) เช่น `เมืองสุราษฎร์ธาน` $\rightarrow$ `เมืองสุราษฎร์ธานี`, `เมืองนครศรีธรรมร` $\rightarrow$ `เมืองนครศรีธรรมราช`, `เมืองประจวบคีรีข` $\rightarrow$ `เมืองประจวบคีรีขันธ์`, `สุไหงโก-ล` $\rightarrow$ `สุไหงโก-ลก`
  - **แก้ไขชื่อย่อและอำเภอเมือง**: `อยุธยา`, `จ.อยุธยา` $\rightarrow$ `พระนครศรีอยุธยา`, `อำเภอ = เมือง` $\rightarrow$ `เมือง{จังหวัด}`
  - **ตัดคำนำหน้าและวงเล็บขยะ**: ตัดคำว่า 'ต.', 'อ.', 'จ.', 'แขวง', 'เขต' และตัดวงเล็บสาขา เช่น `ปทุมธานี(ธัญบุรี)` $\rightarrow$ `ปทุมธานี`
  - **แก้ปัญหาคำซ้อนข้ามจังหวัด (Cross-Province Mismatch)**:
    - ป้องกันข้อผิดพลาด "บางนา-ตราด" ถูกแยกเป็นจังหวัดตราด $\rightarrow$ ปรับคืนเป็น `สมุทรปราการ` (บางพลี) หรือ `กรุงเทพมหานคร` (บางนา)
    - `กันทรลักษ์` ถูกบันทึกเป็น กทม. $\rightarrow$ ปรับคืนเป็น `ศรีสะเกษ`
    - อำเภอต่างจังหวัดที่ติดเป็น กทม. เช่น `ศรีราชา` $\rightarrow$ `ชลบุรี`, `ปากช่อง` $\rightarrow$ `นครราชสีมา`, `ส่องดาว` $\rightarrow$ `สกลนคร`, `ปากเกร็ด/เมืองนนทบุรี` $\rightarrow$ `นนทบุรี`
  - **แมปโซนการตลาดและถนนยอดนิยม (Popular Zones & Roads Mapping)**:
    - ถนนหลังสวน, ซอยต้นสน, ถนนวิทยุ $\rightarrow$ แขวงลุมพินี, เขตปทุมวัน, กทม.
    - รามอินทรา, ท่าแร้ง $\rightarrow$ แขวงท่าแร้ง, เขตบางเขน, กทม.
    - เกษตร-นวมินทร์, นวลจันทร์ $\rightarrow$ เขตบึงกุ่ม, กทม.
    - แจ้งวัฒนะ $\rightarrow$ แขวงทุ่งสองห้อง, เขตหลักสี่, กทม.
  - **จัดระเบียบชื่อตำบลตามมาตรฐานราชการ (Subdistrict Standardization)**:
    - `เมืองพัทยา` (อ.บางละมุง) $\rightarrow$ กำหนดเป็น `หนองปรือ`
    - `แขวงบางนา` เดิม $\rightarrow$ กำหนดเป็น `บางนาเหนือ`
    - `แขวงบางบอน` เดิม $\rightarrow$ กำหนดเป็น `บางบอนเหนือ`
* **ฟังก์ชันจัดการอำเภอภาษาอังกฤษ (`translate_amphoe_en_to_th`)**:
  - แปลงชื่ออำเภอภาษาอังกฤษกลับเป็นภาษาไทย เช่น `Si Racha` $\rightarrow$ `ศรีราชา`, `Muang Chiang Mai` $\rightarrow$ `เมืองเชียงใหม่` และล้างข้อความขยะภาษาอังกฤษออก 100%
* **ฟังก์ชันทำความสะอาดราคา (`clean_price_val`)**:
  - กรองราคาขยะ ราคาต่ำกว่า 500 บาท หรือราคาติดลบออก
  - คลี่ตัวเลขราคาช่วงที่นำมาต่อติดกัน (Glued concatenated price เช่น `1890000021900000` $\rightarrow$ `18,900,000`)
* **ฟังก์ชันสกัดและทำความสะอาดชั้น (`clean_floor_val` & `extract_floor_from_text`)**:
  - สกัดชั้นห้องชุดสำหรับคอนโด (เช่น `12`, `12A`, `G`)
  - สกัดจำนวนชั้นอาคารสำหรับบ้าน/ตึกแถว (เช่น `2 ชั้น`, `3.5 ชั้น`)

---

### 2. โมดูลจัดมาตรฐานชื่อโครงการ ([`clean_project_util.py`](clean_project_util.py))
โมดูลความเร็วสูงสำหรับ Clean, จัดมาตรฐาน (Standardization) และจับคู่ (Harmonization) ชื่อโครงการอสังหาริมทรัพย์:
* **Canonical Brand Dictionary 100+ แบรนด์ดัง**:
  - ตรวจจับและจับคู่ชื่อโครงการจาก Developer ชั้นนำ เช่น Ananda (`Ideo`, `Elio`, `Ashton`), LPN (`ลุมพินี วิลล์`, `ลุมพินี คอนโดทาวน์`), Sansiri (`The Line`, `The Base`, `Dcondo`), AP (`Life`, `Aspire`, `Pleno`), Supalai, Land & Houses, Origin ฯลฯ
* **การตัดขยะที่ไม่ใช่ชื่อโครงการ**:
  - ตัดเลขยูนิต, ชั้น, หมายเลขห้อง, คำโฆษณา (เช่น "ถูกสุดในโครงการ", "พร้อมผู้เช่า", "วิวแม่น้ำ", "ห้องมุม") ออกจากชื่อโครงการ เพื่อให้ชื่อโครงการสะอาดและสามารถนำไป Group By วิเคราะห์สถิติในระบบ SAM Analytics และ Bubble Chart ได้อย่างแม่นยำ

---

### 3. ระบบบันทึก Log และแจ้งเตือนโครงสร้างเว็บ ([`logger_util.py`](logger_util.py))
* **Minimalist Transaction Logging**: บันทึกเฉพาะความเคลื่อนไหวระดับสูง `START`, `FINISH`, และ `ERROR` เพื่อไม่ให้ไฟล์ Log บวม
* **Live HTTP Dashboard Output**: ส่งความเคลื่อนไหวคำขอ HTTP (`[HTTP-REQ]`) ออกทางคอนโซลให้ตัวรันคู่ขนานแสดงผลแบบ Real-time
* **Structural Alert Mechanism (`print_structure_alert`)**: ตรวจจับความผิดปกติของ DOM Selector, HTTP 403/401, โครงสร้าง JSON ที่ขาดหาย และพิมพ์กรอบแจ้งเตือนเตือนภัยสีแดงทันที

---

### 4. ระบบหน่วงเวลาและป้องกัน Timeout ([`timeout_handler.py`](timeout_handler.py) & [`time_window_util.py`](time_window_util.py))
* **Unified Delay Standard (`get_scraper_delay()`)**:
  - มาตรฐานหน่วงเวลาทุก Request ที่ส่งออกภายนอกถูกรวมศูนย์ไว้ที่ `get_scraper_delay()` ใน [`time_window_util.py`](time_window_util.py)
  - **ช่วงเวลาค่ำ (Active Window 18:00 - 06:00 น.)**: หน่วงเวลา `4.0 - 5.0 วินาที` (สุ่ม Jitter)
  - **ช่วงเวลากลางวัน หรือโหมดรันทันที (Daytime / NOW Mode)**: หน่วงเวลาปลอดภัย `8.0 - 9.0 วินาที`
  - รองรับพารามิเตอร์ `--now` / `--test` เพื่อทดสอบระบบได้ทันที
* **Smart Backoff Retry**: หน่วงเวลาทวีคูณเมื่อเจอ 429 Too Many Requests หรือ 503 Service Unavailable
* **Fatal Timeout Guard (`wait_1hr_on_timeout`)**: หากเกิดข้อผิดพลาดต่อเนื่องเกินขีดจำกัด ระบบจะพักการทำงานชั่วคราวและกลับมาลองใหม่โดยอัตโนมัติ

---

## 🏛️ โครงสร้างของแต่ละเว็บไซต์ จัดตามกลุ่มประเภทองค์กร (Platform Specifications by Category)

---

### 🏛️ หมวดที่ 1: หน่วยงานรัฐ / กรมบังคับคดี (Government & Legal Execution)

#### 1. LED - กรมบังคับคดี (`scrape_led_monthly.py`)
- **ประเภทเว็บ**: ASP.NET / ASP Web Forms (Table Search with Session State)
- **Engine**: `AuditedSession` (`requests` with Multi-page Pagination & Province State Management)
- **Base URL**: `https://asset.led.go.th/newbidreg/`
- **Search URL**: `https://asset.led.go.th/newbidreg/default.asp`
- **เทคนิคการดึงข้อมูล**:
  - ดึงค่า `oseckey` และรายชื่อจังหวัดจากหน้าเริ่มต้น
  - ส่ง POST Form request ค้นหาตามรายจังหวัด วนลูปทุกหน้า (`web1` ถึง `web30`)
  - **การคัดกรองทรัพย์ที่ขายได้แล้ว**: ตรวจจับ Hidden fields `issale1` ถึง `issale8` และ `issale` หากพบค่า `'1'` (ขายได้แล้ว) จะทำการ **ข้าม (Skip)** ทันที
  - **State Guard**: บันทึกสถานะจังหวัดที่ทำเสร็จใน `.led_state_{MONTH}.json` และตรวจสอบยอดรวม (> 30,000 รายการ)
- **Field Mapping (23 คอลัมน์)**:
  - `ID`: `auc_asset_gen` หรือ `{law_suit_no}/{law_suit_year}_{str_bid_num}`
  - `รหัสทรัพย์`: คดีหมายเลขแดง/ลำดับทรัพย์
  - `ประเภทการขาย`: `saletypename` (`ขายทอดตลาด ปลอดจำนอง`, `ขายทอดตลาด จำนองติดไป`)
  - `ราคา`: ค้นหาราคาประเมินที่ไม่เป็น 0 จาก `assetprice1` ถึง `assetprice9`
  - `ที่อยู่`: `tumbol_name`, `amphur_name`, `province_name`
  - `เนื้อที่`: `rai`, `quaterrai`, `wa`
  - `พื้นที่ใช้สอย`: สำหรับห้องชุด/คอนโด สกัดจาก `wa` (ตร.ม.) และตัดคำว่าระเบียงออกเสมอ
  - `ชั้น`: สกัดจาก `remark`, `landdesc`, หรือชื่อประกาศผ่าน `extract_floor_from_text`
  - `เลขโฉนด`: **สกัดจาก `extract_deed_no(data)`**
  - `ลิงก์`: **`app/static/led_bridge.html?suit_no=...&suit_year=...`** (Bridge URL เพื่อป้องกันปัญหาหน้าค้นหาหมดอายุ)

---

### 🏢 หมวดที่ 2: บริษัทบริหารสินทรัพย์ (Asset Management Companies - AMC)

#### 2. SAM - บริษัท บริหารสินทรัพย์สุขุมวิท จำกัด (`scrape_sam_monthly.py`)
- **ประเภทเว็บ**: PHP Search Backend + Detail HTML Page
- **Engine**: `AuditedSession` (`requests`) + `BeautifulSoup` + Single Polite Worker
- **Listing Endpoint**: `POST https://sam.or.th/site/npa/page_list.php`
- **Detail Endpoint**: `GET https://sam.or.th/site/npa/detail.php?id={prop_id}&keyref=`
- **เทคนิคการดึงข้อมูล**:
  - ดึงรายการจากหน้า List และดึงรายละเอียด ละติจูด ลองจิจูด จาก Google Maps Embed ในหน้า Detail
  - **การจัดการทรัพย์รอประกาศราคา**: หากทรัพย์ระบุประเภทการขายว่า "รอประกาศราคา" ระบบจะล้างค่าราคาเป็น `None` ทันทีเพื่อป้องกันการนำราคาเก่า/ราคาแคชมาแสดงผล
- **Field Mapping (22 คอลัมน์)**:
  - `ID` / `รหัสทรัพย์`: `รหัสทรัพย์สิน : XXXXX`
  - `ประเภททรัพย์`: `ประเภททรัพย์สิน : ...`
  - `ราคา`: `ราคาประกาศขาย : ...` (ถ้า "รอประกาศราคา" ให้เป็น `None`)
  - `ที่อยู่`: สกัดจากข้อความที่ตั้ง `ตำบล... อำเภอ... จังหวัด...`
  - `พิกัด`: สกัดจาก Google Maps Embed link ในหน้า Detail
  - `ชั้น`: สกัดจาก `ชั้นที่ : ...` หรือสกัดจากข้อความประกาศ
  - `วันประกาศ`: สกัดจากวันที่ประกาศ/วันที่ปรับปรุง

---

#### 3. BAM - บมจ.บริหารสินทรัพย์ กรุงเทพพาณิชย์ (`scrape_bam_monthly.py`)
- **ประเภทเว็บ**: Server-rendered Search Page + Detail Page Scraping
- **Engine**: `AuditedSession` (`requests`) + `BeautifulSoup` + Polite Sequential Detail Loop
- **Listing URL**: `https://www.bam.co.th/th/npa/property/search?page={page}`
- **Detail URL**: `https://www.bam.co.th/th/npa/property/{item_id}`
- **Items Per Page**: 24 รายการ/หน้า (~18,000+ รายการ)
- **เทคนิคการดึงข้อมูล**:
  - สกัดรายการทรัพย์และ metadata จาก JSON state ใน HTML หน้าค้นหา
  - ดึงข้อมูลพิกัด ที่อยู่ละเอียด และข้อมูลชั้นเพิ่มเติมจากหน้ารายละเอียดทรัพย์ (Detail Page)
- **Field Mapping (22 คอลัมน์)**:
  - `ID` / `รหัสทรัพย์`: รหัสทรัพย์ BAM เช่น `HP-XXXXX`
  - `ราคา`: สกัดจาก `price` หรือ `specialPrice`
  - `ที่อยู่`: ดึงจากหน้ารายละเอียดร่วมกับตำบล/อำเภอ/จังหวัดในหน้าค้นหา
  - `พิกัด`: สกัดจากพิกัดหน้ารายละเอียด Detail
  - `เนื้อที่`: แยกคำนวณ ไร่-งาน-วา ผ่าน `format_land_area`
  - `ชั้น`: สกัดจาก `floor`/`floors`/`totalFloors` หรือสกัดจากข้อความชื่อประกาศ
  - `วันประกาศ`: `created_at` หรือ `postDate`

---

#### 4. Chayo555 - ชโย กรุ๊ป (`scrape_chayo555_monthly.py`)
- **ประเภทเว็บ**: Asset Listing Web Portal
- **Engine**: `AuditedSession` (`requests`) + `BeautifulSoup` + Offline GIS Engine
- **Listing URL**: `https://asset.chayo555.com/search`
- **เทคนิคการดึงข้อมูล**:
  - สแกน Categories และ Widgets ทั้งหมดเพื่อรวบรวม URL ทรัพย์ที่ไม่ซ้ำกัน
  - ดึงหน้ารายละเอียดทรัพย์ (Detail Page) ทีละรายการแบบ Single Worker Throttling เพื่อความเสถียร
- **Field Mapping (22 คอลัมน์)**:
  - `ID` / `รหัสทรัพย์`: สกัดจากคีย์เวิร์ด `รหัสทรัพย์สิน` ในหน้าประกาศ
  - `ราคา`: สกัดจาก `ราคาขาย`
  - `ที่อยู่ & พิกัด`: สกัดจากหน้าประกาศและแปลงพิกัดผ่าน GIS Engine
  - `ชั้น`: สกัดจากสเปครายละเอียดตัวทรัพย์
  - `เนื้อที่`: แปลงผ่าน `convert_to_rai_ngan_wah`

---

### 🏦 หมวดที่ 3: สถาบันการเงิน / ธนาคาร (Financial Institutions & Banks)

#### 5. GHB - ธนาคารอาคารสงเคราะห์ (`scrape_ghb_monthly.py`)
- **ประเภทเว็บ**: Server-rendered HTML + Detail Page GPS Coordination
- **Engine**: `AuditedCurlSession` (`curl_cffi` Impersonate: `chrome120`) + `BeautifulSoup` + Offline GIS
- **Listing URL**: `https://www.ghbhomecenter.com/property-for-sale?pg={page_no}`
- **Detail URL**: `https://www.ghbhomecenter.com/property-{pid}`
- **Items Per Page**: 20 รายการ/หน้า (~30,000+ รายการ)
- **เทคนิคการดึงข้อมูล**:
  - ในหน้าการ์ดผลการค้นหา มีข้อมูลรหัสทรัพย์ ราคา และที่อยู่แบบย่อ
  - **พิกัด GPS จริง (Lat/Lon)**: ดึงจากหน้ารายละเอียด (`/property-{pid}`) ผ่านพิกัด Google Maps ในรูปแบบ `google.com/maps.*?q=([0-9\.]+),([0-9\.]+)` (มีความครอบคลุมของพิกัดจริงสูงถึง ~90%)
  - ข้อมูลที่ไม่มีพิกัดจะส่งต่อให้ `clean_row_location()` เพื่อทำ Centroid Imputation
- **Field Mapping (22 คอลัมน์)**:
  - `ID`: รหัสตัวเลขจาก URL `/property-{pid}`
  - `ราคา`: สกัดจาก `class="text-propertyprice"`
  - `ที่อยู่`: สกัดจาก card description และคลีนผ่านโมดูลที่อยู่
  - `ชั้น`: สกัดจากสเปคบ้าน/คอนโดผ่าน `clean_floor_val` / `extract_floor_from_text`

---

#### 6. KBANK - ธนาคารกสิกรไทย NPA (`scrape_kbank_monthly.py`)
- **ประเภทเว็บ**: ASP.NET Web Service + Akamai Interstitial Challenge
- **Engine**: `AuditedCurlSession` (`curl_cffi` Impersonate: `chrome120`)
- **Security / WAF**: Akamai Interstitial POW Solver (`solve_akamai_challenge`) จัดการแก้โจทย์ POW และส่งผลลัพธ์ผ่าน `/_sec/verify?provider=interstitial`
- **Endpoint**: `POST https://www.kasikornbank.com/Custom/KWEB2020/NPA2023Backend13.aspx/GetProperties`
- **Payload**:
  ```json
  {
    "filter": {
      "AllCurrentPageIndex": 1,
      "CurrentPageIndex": 1,
      "PageSize": 50,
      "SearchPurposes": ["AllProperties"],
      "propertyList": "AllProperties"
    }
  }
  ```
- **Field Mapping (22 คอลัมน์)**:
  - `ID` / `รหัสทรัพย์`: `item.PropertyCode` หรือ `item.PropertyId`
  - `ชื่อโครงการ`: `item.ProjectName`
  - `ประเภททรัพย์`: `item.PropertyTypeDesc`
  - `ราคา`: `item.SpecialPrice` หรือ `item.Price`
  - `ที่อยู่`: `item.SubDistrictName`, `item.DistrictName`, `item.ProvinceName`
  - `พิกัด`: `item.Latitude`, `item.Longitude`
  - `ชั้น`: สกัดจาก `FloorTH`, `Floor`, `TotalFloor` หรือหน้ารายละเอียดทรัพย์ผ่าน `fetch_kbank_detail_floor`
  - `ลิงก์`: `https://www.kasikornbank.com/th/propertyforsale/search/pages/detail.aspx?PropertyCode={PropertyCode}`

---

#### 7. KTB - ธนาคารกรุงไทย NPA (`scrape_ktb_monthly.py`)
- **ประเภทเว็บ**: REST API (JSON POST Endpoint) + Browser Session Simulation
- **Engine**: `AuditedSession` (`requests`) พร้อม `init_browser_session()` จำลองการเปิดเว็บเพื่อรับคุกกี้ที่ถูกต้อง
- **Endpoint**: `POST https://npa.krungthai.com/api/v1/product/searchAll`
- **Headers**: `Origin: https://npa.krungthai.com`, `Referer: https://npa.krungthai.com/searchResult`
- **Request Payload**:
  ```json
  {
    "paging": {
      "currentPage": 1,
      "rowsPerPage": 50,
      "totalRows": 0
    }
  }
  ```
- **Field Mapping (23 คอลัมน์)**:
  - `ID` / `รหัสทรัพย์`: `item.collGrpId` หรือ `item.collCode`
  - `ชื่อโครงการ`: `item.propertyName`
  - `ประเภททรัพย์`: `item.collCateName` หรือ `item.assetTypeDetail` หรือ `item.collTypeName`
  - `ราคา`: `item.price` หรือ `item.nmlPrice` หรือ `item.priceNumber`
  - `ที่อยู่`: `item.shrTambonName`, `item.shrAmphurName`, `item.shrProvinceName`
  - `พิกัด`: `item.lat`, `item.lon`
  - `เนื้อที่`: แปลงจาก `item.area` หรือ `item.calSumAreaCollGrpId` ผ่าน `parse_rai_ngan_wah`
  - `พื้นที่ใช้สอย`: `item.sumAreaNum`
  - `ชั้น`: `item.floorNum` หรือ `item.floor` หรือสกัดจากข้อความ
  - `วันประกาศ`: `item.priceStrDt`
  - `ยอดเข้าชม`: **`item.productCountView`**
  - `ลิงก์`: `item.shareURL` หรือ `https://npa.krungthai.com/propertyDetail/{p_code}`

---

#### 8. SCB - ธนาคารไทยพาณิชย์ Home SCB (`scrape_scb_monthly.py`)
- **ประเภทเว็บ**: REST API (AJAX JSON Endpoint)
- **Engine**: `AuditedSession` (`requests`) พร้อม HTTPAdapter Connection Pool
- **Endpoint**: `GET https://asset.home.scb/api/project/cmd`
- **Query Params**: `type=project&page={page}&limit=50&sortBy=all&command=get_project`
- **Response Format**: `{"s": "y", "total": 1234, "d": [...]}`
- **Field Mapping (22 คอลัมน์)**:
  - `ID`: `item.project_id`
  - `ชื่อโครงการ`: `item.project_name`
  - `ประเภททรัพย์`: `item.property_type_name`
  - `ราคา`: `item.special_price` หรือ `item.sale_price`
  - `ที่อยู่`: สกัดจาก `item.address_full` ด้วย Regex หรือฟิลด์ `province_name`, `district_name`, `subdistrict_name`
  - `พิกัด`: `item.lat`, `item.lng`
  - `ชั้น`: สกัดจาก `item.floor`/`floors`/`total_floor` หรือสกัดจากข้อความ
  - `วันประกาศ`: `item.create_date`
  - `ลิงก์`: `https://asset.home.scb/project/{project_id}`

---

#### 9. GSB - ธนาคารออมสิน NPA (`scrape_gsb_monthly.py`)
- **ประเภทเว็บ**: Next.js Static Build Data API (`x-nextjs-data: 1`) + Detail Enrichment
- **Engine**: `AuditedSession` (`requests.Session`) + Dynamic `buildId` extraction
- **Build ID Extraction**: ดึง Build ID อัตโนมัติจากหน้าแรก `https://npa-assets.gsb.or.th/`
- **Data Endpoint**: 
  - `https://npa-assets.gsb.or.th/asset/npa/all?page=1&page_size=5000&asset_type_dev=npa`
- **Detail Page Coordinates & Subtype**:
  - ดึงพิกัดจริงจาก `__NEXT_DATA__` และ Google Maps URL ในหน้ารายละเอียดทรัพย์ (`fetch_gsb_detail_coords`)
- **Field Mapping (23 คอลัมน์)**:
  - `ID`: `item.asset_id` หรือ `item.id`
  - `รหัสทรัพย์`: `item.asset_group_id_npa` หรือ `item.asset_group_id`
  - `ประเภททรัพย์`: `extract_gsb_property_type(subtype, main_type)`
  - `ราคา`: `item.xprice` $\rightarrow$ `item.current_offer_price` $\rightarrow$ `item.xprice_normal`
  - `ที่อยู่`: `item.sub_district_name`, `item.district_name`, `item.province_name`
  - `พิกัด`: พิกัดจริงจากหน้า Detail หรือจากฟิลด์ `latitude`/`longitude` ใน JSON
  - `เนื้อที่`: แปลง `sum_rai`, `sum_ngan`, `sum_square_wa`
  - `ชั้น`: สกัดจาก `floor`/`floors`/`total_floor`/`number_of_floors` หรือคำอธิบายทรัพย์
  - `เลขโฉนด`: **`item.deed_info`** (สำหรับเชื่อมโยง LandsMaps)

---

### 🌐 หมวดที่ 4: พอร์ทัลและมาร์เก็ตเพลสอสังหาริมทรัพย์ (Property Portals & Marketplaces)

#### 10. DDproperty (`scrape_ddproperty_monthly.py`)
- **ประเภทเว็บ**: Next.js / React SSR Listing + Detail Page Coordinates & Floor Enrichment
- **Engine**: `AuditedCurlSession` (`curl_cffi` Impersonate: `chrome120`) + `BeautifulSoup` + Offline GIS
- **State Management**: บันทึกหน้าและรายการที่ดึงแล้วผ่านไฟล์ `.ddproperty_state_{MONTH}.json` รองรับการ Resume สแครปต่อได้ทันที
- **Listing URL**: `https://www.ddproperty.com/รวมประกาศขาย/{page}`
- **Detail URL**: `https://www.ddproperty.com/property/{slug-id}`
- **Items Per Page**: 20 รายการ/หน้า (~110,000+ รายการ)
- **เทคนิคการดึงข้อมูล**:
  - ใช้ `curl_cffi` จำลองเบราว์เซอร์ Chrome 120 เพื่อผ่านระบบคัดกรองบอท (Cloudflare / WAF) อย่างมีเสถียรภาพ
  - สกัดข้อมูลจากการ์ดประกาศและ JSON-LD Schema
  - **การดึงพิกัดจริงและชั้น (`fetch_ddproperty_detail_coords`)**:
    - ยิงขอหน้า Detail (`/property/{id}`) โดยตั้งค่า Referer เพื่อดึงข้อมูลจาก `__NEXT_DATA__`:
      - พิกัด GPS จริงจาก `listingLocationData.data.center` (`lat`, `lng`)
      - ชั้นยูนิตคอนโดจาก `descriptionBlockData.description` และ `detailsData.metatable.items`
  - หากไม่มีพิกัดจริง ระบบจะทำ Centroid Imputation ผ่าน `clean_row_location()`
- **Field Mapping (22 คอลัมน์)**:
  - `ID`: รหัสทรัพย์จาก URL/Card ID
  - `ชื่อโครงการ`: สกัดจากชื่อประกาศ/โครงสร้าง HTML
  - `ราคา`: สกัดจาก Element ราคา (`฿...`)
  - `ชั้น`: สกัดจากหน้า Detail ร่วมกับ `extract_floor_from_text`
  - `วันประกาศ`: สกัดจาก `สร้างเสร็จ` / `โพสต์เมื่อ` / `อัปเดตเมื่อ`

---

#### 11. Livinginsider (`scrape_livinginsider_monthly.py`)
- **ประเภทเว็บ**: Next.js Paginated Real Estate Portal + Internal API Detail Enrichment + Dual-Layer GPS & GIS Architecture
- **Engine**: `AuditedCurlSession` (`curl_cffi` Impersonate: `chrome120`) + `BeautifulSoup` + Offline GIS Point-in-Polygon Engine
- **State & Failed Recovery**: บันทึกหน้าที่มีปัญหาลงใน `logs/{MONTH}/livinginsider_failed_pages.json` เพื่อนำกลับมาสแครปซ้ำจนครบ 100%
- **Listing URL (หน้าค้นหา)**:
  - `https://www.livinginsider.com/property-buysell/{page_num}`
  - ส่งค่า `48` รายการ/หน้า (มีรายการอสังหาริมทรัพย์รวมกว่า ~136,000+ รายการ)
- **Detail Endpoints & เทคนิคการข้ามผ่าน CloudFront WAF Challenge**:
  - **URL หน้าเว็บทั่วไป**: `https://www.livinginsider.com/detail/{slug}-{item_id}` — *ข้อควรระวัง*: หากส่ง Request ไปยัง URL นี้ตรงๆ จากภายนอกจะติด **AWS CloudFront WAF JavaScript Challenge (HTTP 202)** ทำให้โปรแกรมสแครปเปอร์ทั่วไปอ่านข้อมูลไม่สำเร็จ
  - **Internal API Endpoint (ทางลัดความเร็วสูง)**:
    ```
    GET https://www.livinginsider.com/api/detail/{item_id}
    ```
    - Header ที่จำเป็น: `Referer: https://www.livinginsider.com/property-buysell`
    - ผลลัพธ์: ส่ง HTML ของหน้ารายละเอียดทรัพย์ฉบับสมบูรณ์กลับมาด้วยสถานะ **HTTP 200 OK ทันที (ไม่ติด WAF Challenge)** ใช้เวลาโหลดเพียง ~200–300ms
- **แหล่งที่มาและการสกัดข้อมูลในหน้ารายละเอียด (`api/detail/{item_id}`)**:
  1. **พิกัด GPS จริง (Real Latitude / Longitude)**:
     - **React Component State / Next.js Hydration**: ค้นหาตัวแปรพิกัดในแท็ก `<script>` ของ Next.js เช่น `latitude:\s*([\d\.]+)`, `longitude:\s*([\d\.]+)` หรือ `lat:\s*([\d\.]+)`, `lng:\s*([\d\.]+)`
     - **Google Maps Embed / Query Parameter**: สกัดจาก URL เชื่อมต่อแผนที่ Google Maps ในแท็ก `<iframe>` หรือ `<a>` เช่น `maps.google.com.*?center=([\d\.]+),([\d\.]+)`, `q=([\d\.]+),([\d\.]+)`, `ll=([\d\.]+),([\d\.]+)` หรือ `destination=([\d\.]+),([\d\.]+)`
     - **HTML Data Attributes**: ค้นหาแอตทริบิวต์ `data-lat="..."`, `data-lng="..."`
     - **Schema.org JSON-LD**: สกัดจาก `@type: "GeoCoordinates"` (`latitude`, `longitude`)
  2. **การทำ Offline GIS Reverse-Geocoding ทันทีเมื่อได้พิกัดจริง**:
     - เมื่อสกัดได้พิกัด GPS จริง ระบบจะส่งเข้าฟังก์ชัน `reverse_geocode_location(lat, lng)` เพื่อจับคู่พิกัดกับขอบเขตเวกเตอร์ `subdistricts.geojson` และ `districts.geojson` ในหน่วยความจำ RAM (<0.1ms)
     - ได้ชื่อ **ตำบล, อำเภอ, จังหวัด ที่ถูกต้องตามทะเบียนการปกครอง 100%** แก้ปัญหาชื่อทำเลไม่เป็นทางการบนหน้าเว็บ
  3. **การแก้ปัญหา Breadcrumb Noise & Livinginsider Zone Mapping (สำหรับรายการที่ไม่มีหมุด GPS)**:
     - **กรอง Breadcrumb ขยะ**: ใน Breadcrumb JSON-LD (`@type: BreadcrumbList`) ของเว็บ Livinginsider จะมีแท็ก `"รายการ ขาย ให้เช่า"` หรือชื่อหัวข้อประกาศยาวๆ แทรกเข้ามา ระบบจะทำการกรองออกเพื่อไม่ให้เขียนทับชื่ออำเภอ
     - **พจนานุกรมแปลงโซน (`LIVING_ZONE_TO_LOCATION`)**: แปลงชื่อโซนทำเลยอดนิยมของ Livinginsider (เช่น `pinklao-charansanitwong` $\rightarrow$ บางกอกน้อย กรุงเทพฯ, `pak-chong-khaoyai` $\rightarrow$ ปากช่อง นครราชสีมา, `bang-kae-phetkasem` $\rightarrow$ บางแค กรุงเทพฯ, `ratchadapisek-huaikwang-suttisan` $\rightarrow$ ห้วยขวาง กรุงเทพฯ ฯลฯ)
     - **Centroid Imputation**: ส่งชื่ออำเภอและจังหวัดที่ได้เข้าฟังก์ชัน `clean_row_location()` เพื่อคำนวณจุดกึ่งกลางผ่าน GIS ทำให้ประกาศที่ผู้ขายไม่ได้ปักหมุด GPS ยังคงมีพิกัดระดับอำเภอได้อย่างถูกต้อง ครบถ้วน 100%
  4. **การสกัดข้อมูลเฉพาะของ Livinginsider**:
     - **วันประกาศ (`วันประกาศ`) & สถาปัตยกรรมป้องกัน ReDoS (Regular Expression Catastrophic Backtracking)**:
       - **ระดับที่ 1 (High Priority & ReDoS-Safe)**: ดึงจาก Structured Schema ใน JSON-LD / API State (`datePosted`, `create_date`, `created_at`, `post_date`) ซึ่งมีรูปแบบ ISO Date (`YYYY-MM-DD`) แปลงเป็น `DD/MM/YYYY` พ.ศ. โดยตรง (รวดเร็ว <0.01 วินาที และไม่มีปัญหา Regex Backtracking)
       - **ระดับที่ 2 (Bounded-Window Text Extraction)**: หากไม่มีใน JSON จะค้นหาจากข้อความรอบคำว่า `สร้างเมื่อ`, `วันที่ประกาศ`, `อัปเดตเมื่อ`, `ลงประกาศเมื่อ` โดยจำกัดความยาวหน้าต่างค้นหาไม่เกิน 300 ตัวอักษรรอบตำแหน่งคีย์เวิร์ด และล้างแท็ก HTML ออกก่อน เพื่อตัดปัญหา Regex ติดลูป Backtracking ข้ามบล็อก HTML ขนาดใหญ่ (~500+ KB) เด็ดขาด
       - **ระดับที่ 3 (Relative Date Parser)**: รองรับการแปลงข้อความเวลาสัมพัทธ์ เช่น `1 week ago`, `3 days ago`, `เมื่อวานนี้`, `วันนี้` เป็นวันที่จริงและคำนวณเป็นปี พ.ศ. อัตโนมัติ
     - **ยอดเข้าชม (`ยอดเข้าชม`)**: สกัดจากตัวแปร `views: (\d+)` ในสคริปต์หน้าเว็บ หรือตัวเลขใต้การ์ด
     - **ยอดคลิก (`ยอดคลิก`)**: สกัดจากตัวแปร `clicks: (\d+)` ในสคริปต์หน้าเว็บ
     - **ชั้น (`ชั้น`)**: สกัดจากข้อมูลสเปคและข้อความหัวข้อประกาศผ่านฟังก์ชัน `extract_floor_from_text`
- **Field Mapping (24 คอลัมน์)**:
  - `ID`: รหัสตัวเลขประกาศจาก URL เช่น `3265978`
  - `รหัสทรัพย์`: ใช้รหัสประกาศเดียวกับ `ID`
  - `ชื่อโครงการ`: สกัดจาก `span.line-clamp-1` หรือ Breadcrumbs
  - `ราคา`: สกัดจาก Element ราคา (`฿...`)
  - `พิกัด (ละติจูด, ลองจิจูด)`: ดึงพิกัดจริงจากหน้าเว็บ หรือจุดกึ่งกลางโซนอำเภอผ่าน Offline GIS (ความครอบคลุม 100%)
  - `ที่อยู่ (ตำบล, อำเภอ, จังหวัด)`: ได้รับการรับรองและทำความสะอาดผ่าน GIS Engine โดยไม่มีตัวอักษรภาษาอังกฤษหรือตัวเลขปะปนในช่องอำเภอ
  - `ชั้น`: สกัดจากสเปคในการ์ด หรือจากข้อความในหน้ารายละเอียด
  - `วันประกาศ`: ดึงจากวันสร้างหรือวันอัปเดตประกาศ
  - `ยอดเข้าชม`: สกัดจากสถิติ `views`
  - `ยอดคลิก`: สกัดจากสถิติ `clicks`
  - `ลิงก์`: URL ประกาศหน้าเว็บจริง (`https://www.livinginsider.com/detail/{slug}-{id}`) สำหรับให้ผู้ใช้งานคลิกเปิดดูได้สะดวก

---

#### 12. NaYoo - น่าอยู่ (`scrape_nayoo_monthly.py`)
- **ประเภทเว็บ**: Modern Multi-tenant REST API
- **Engine**: `AuditedSession` (`requests`)
- **API Base**: `https://api.nayoo.co`
- **API Key**: ส่งผ่าน Header `apikey: bf78c26f3bde3729d957df5e00682b4f67e15dcb1ef0a62127403669b0d01ee3`
- **เทคนิคการดึงข้อมูล**:
  - ดึงรายการทรัพย์และเชื่อมต่อหน้ารายละเอียด (`detail_data`) เพื่อดึงข้อมูล `spec` (ห้องนอน, ห้องน้ำ, ที่จอดรถ, ชั้น)
  - ระบบ Sanity Check ราคา: ป้องกันความผิดพลาดจากการกรอกราคาล้านแบบพิมพ์เลขตกหล่น (เช่น ตัวเลขเกินพันล้าน จะทำการจับคู่คำว่า "ล้านบาท" ในข้อความเพื่อปรับราคาให้ถูกต้อง)
- **Field Mapping (24 คอลัมน์)**:
  - `ID`: `item.id` หรือ `item.uuid`
  - `ชื่อโครงการ`: `item.project_name.th` หรือ `item.title`
  - `ประเภททรัพย์`: จัดกลุ่มผ่าน `normalize_prop_type`
  - `ราคา`: `pricing.sale_price` $\rightarrow$ `start_price` $\rightarrow$ `promotion_price`
  - `ที่อยู่ & พิกัด`: ดึงจากข้อมูลพิกัดและ Reverse Geocode ผ่าน GeoJSON
  - `ชั้น`: สกัดจาก `spec.floor` หรือสกัดจากข้อความประกาศ
  - `วันประกาศ`: `published_at` หรือ `created_at`
  - `เลขโฉนด`: รองรับฟิลด์คอลัมน์มาตรฐาน
  - `ยอดเข้าชม`: **`item.views` หรือ `detail_data.views`**
  - `ลิงก์`: `https://nayoo.co/property-for-sale/properties/{p_slug}/{item_slug}`

---

#### 13. ZmyHome (`scrape_zmyhome_monthly.py`)
- **ประเภทเว็บ**: Server-rendered SSR Web Application (Pagination Cap: 99 หน้า/หมวด)
- **Engine**: `AuditedSession` (`requests`) + `BeautifulSoup` + Polite Sequential Detail Loop
- **สถาปัตยกรรมการดึงข้อมูล (Full Coverage By-Province Architecture)**:
  - สแครปครอบคลุม **77 จังหวัดทั่วประเทศ** (ID: 1–77) แยกตาม **6 หมวดหมู่ทรัพย์สิน** (`condo`, `house`, `townhome`, `land`, `homeoffice`, `npa`) เพื่อทะลุขีดจำกัดการแสดงผลหน้าเว็บรวม (ที่แสดงได้สูงสุดเพียง 99 หน้า ~3,465 รายการ) ทำให้เก็บประกาศได้ครบถ้วนทั่วประเทศ
  - **Listing URL**: `https://zmyhome.com/buy/{p_type}/province/{prov_id}?page={page}&sortFilter=ads&per-page=35`
  - **Detail URL**: `https://zmyhome.com/property/{item_id}`
  - **Pagination Cap**: ระบบ Backend ของ ZmyHome จำกัดการเปิดดูที่หน้า 99 ต่อหมวด (`max_page = min(99, max(pages))`) หากเปิดหน้า 100 ขึ้นไป เซิร์ฟเวอร์จะตอบกลับ HTTP 404 โดยอัตโนมัติ
- **ระบบ Streaming Auto-Save & Data Integrity (การันตีข้อมูลไม่สูญหาย)**:
  - **Initial CSV Init**: สร้างโครงสร้างไฟล์ CSV พร้อม Header มาตรฐานตั้งแต่เริ่มโปรแกรมทันที 100%
  - **Batch Flush ระหว่างหน้าแรก**: บันทึกข้อมูลลงดิสก์ทุกๆ 5 รายการ เพื่อให้เห็นความคืบหน้าต่อเนื่องตั้งแต่ 40 วินาทีแรก
  - **Per-Page Flush**: บันทึกซ้ำลงไฟล์ CSV ทันทีในทุกๆ หน้าที่กวาดเสร็จ
  - **Emergency Shutdown Handler (`atexit` + Signal)**: มีตัวดักจับสัญญาณเมื่อผู้ใช้สั่งหยุดหรือปิดโปรแกรมกะทันหัน (`Ctrl+C` หรือปิดหน้าต่าง) โดยจะ Flush ข้อมูลสะสมทั้งหมดในหน่วยความจำลง CSV ให้ทันทีก่อนกระบวนการสิ้นสุด
  - **Real-time Console Progress**: แสดงผลสถานะสดหน้าต่อหน้า (จังหวัด, หมวดทรัพย์, หน้าที่ทำ, จำนวนทรัพย์ที่เพิ่ม, จำนวนสะสม และสถานะการบันทึกไฟล์)
- **GIS Reverse Geocoding**: เชื่อมต่อ [`clean_location_util.py`](clean_location_util.py) ทำงานร่วมกับ In-Memory `shapely.strtree.STRtree` + `subdistricts.geojson` (`init_gis()`, `reverse_geocode_location()`, `clean_row_location()`) แปลงพิกัดจริง Lat/Lng บนเว็บเป็น ตำบล/อำเภอ/จังหวัด ใน RAM รวดเร็ว <0.1ms ออฟไลน์ 100%
- **ระบบป้องกันข้อมูลซ้ำซ้อนจาก SAM (SAM Anti-Duplicate Filter)**:
  - ZmyHome มีทรัพย์ฝากขายของ บสส. (SAM) อยู่เป็นจำนวนมาก
  - ฟังก์ชัน `is_sam_property()` จะตรวจสอบทั้ง JSON-LD Schema (`"seller": {"name": "SAM SAM"}`) และคีย์เวิร์ด "ทรัพย์สินรอการขายของ บสส.", "SAM" หากพบจะทำการ **ข้าม (Skip)** ไม่ดึงข้อมูล เพื่อให้ข้อมูลของ SAM มาจากต้นทาง `scrape_sam_monthly.py` เพียงแหล่งเดียว
- **Field Mapping (23 คอลัมน์)**:
  - `ID` / `รหัสทรัพย์`: รหัสทรัพย์จาก URL เช่น `V206959`, `H451280`
  - `ชื่อโครงการ`: สกัดจาก `info-project` Section หรือทำความสะอาดจากข้อความหัวข้อประกาศผ่าน [`clean_project_util.py`](clean_project_util.py)
  - `ประเภททรัพย์`: แปลงจากหมวดค้นหา (`ห้องชุดพักอาศัย`, `บ้านเดี่ยว`, `ทาวน์เฮ้าส์/ทาวน์โฮม`, `ที่ดิน`, `อาคารพาณิชย์/โฮมออฟฟิศ`, `ทรัพย์รอการขาย`)
  - `ราคา`: สกัดจาก Card Price / JSON-LD Offer (`priceSpecification`) ปรับหน่วยล้านบาทอัตโนมัติ
  - `ที่อยู่`: Reverse geocode จากพิกัด Lat/Lng ผ่าน Shapely STRtree In-Memory GIS 100%
  - `พิกัด`: สกัดจาก Google Maps Embed link หรือตัวแปร Leaflet ในหน้า Detail
  - `ชั้น`: สกัดจากสเปคยูนิตในหน้า Detail หรือสกัดด้วย Regex ผ่าน `extract_floor_from_text`
  - `ยอดเข้าชม`: **สกัดจากตัวเลขข้างไอคอนรูปตา (`bi-eye`)**
  - `วันประกาศ`: สกัดจาก "ลงประกาศเมื่อ" / "อัปเดตเมื่อ"
---

#### 14. Baania (`scrape_baania_monthly.py`)
- **ประเภทเว็บ**: Next.js SSR Web Application (ElasticSearch Backend Payload)
- **Engine**: `AuditedCurlSession` (`curl_cffi` Impersonate: `chrome120`)
- **Listing URL**: `https://www.baania.com/s/%E0%B8%97%E0%B8%B1%E0%B9%89%E0%B8%87%E0%B8%AB%E0%B8%A1%E0%B8%94/listing?sellState=on-sale,sale-rent&sort.created=asc&page={page}`
- **Items Per Page**: 48 รายการ/หน้า (จำกัดสูงสุด 208 หน้า ~ 10,000 รายการตาม ElasticSearch window)
- **เทคนิคการดึงข้อมูล**:
  - ดึง HTML แล้วใช้ Regex สกัด JSON จาก `<script id="__NEXT_DATA__" type="application/json">(.*?)</script>`
  - ดึงรายการจาก Path: `props.pageProps.defaultData.hits.hits`
- **Field Mapping (22 คอลัมน์)**:
  - `ID`: `item._id` หรือ `_source.view_data.pkid`
  - `รหัสทรัพย์`: `_source.view_data.code` (หากว่างใช้ `ID`)
  - `ชื่อโครงการ`: `_source.view_data.project_title.th`
  - `ชื่อประกาศ`: `_source.view_data.title.th`
  - `ประเภททรัพย์`: `_source.view_data.property_type[].th`
  - `ประเภทการขาย`: แปลงจาก `_source.view_data.sell_state` หรือ `_source.view_data.listing_type`
  - `ราคา`: `_source.view_data.price_start` $\rightarrow$ `price` $\rightarrow$ `price_rent`
  - `ที่อยู่`: ตำบล/อำเภอ/จังหวัด จาก `_source.address`
  - `พิกัด`: `_source.location.lat`, `_source.location.lon`
  - `เนื้อที่`: แปลง `_source.view_data.area_total` (`rai`, `ngan`, `wa`) เป็น `ไร่-งาน-ตร.ว.`
  - `พื้นที่ใช้สอย`: `_source.view_data.area_usable`
  - `ลิงก์`: `https://www.baania.com/th/{url.source_url}` หรือ `/listing/{slug|id}`
  - `ชั้น`: สกัดจาก `view_data.floor` / `floors` ผ่าน `clean_floor_val` หรือสกัดจากข้อความด้วย `extract_floor_from_text`
  - `วันประกาศ`: `_source.filter.created` หรือ `_source.view_data.created_at`
  - `ห้องนอน/ห้องน้ำ/ที่จอดรถ`: `bedroom`, `bathroom`, `parking`

---

## 🛡️ กฎการทำงานคู่ขนานและการผสานข้อมูล (Parallel Orchestration & Merge Rules)

### 1. Parallel Execution Engine ([`run_parallel_monthly.py`](run_parallel_monthly.py))
- รันสแครปเปอร์ทั้ง 14 ค่ายพร้อมกันอย่างเป็นอิสระ โดยมีตัวควบคุม Memory และ Rate Limiter
- ตรวจจับ Session / WAF Error และระบบ Smart Retry อัตโนมัติ
- สรุปผลการทำงานเปรียบเทียบกับเดือนก่อนหน้า และแจ้งเตือนสถานะสำเร็จ/ล้มเหลวแบบ Real-time

### 2. Smart Resume Validation & Streaming Auto-Save
- เมื่อโหลดไฟล์ CSV สะสมเดิม หากพบว่าข้อมูลเดิมมากกว่า 50% มีค่าว่างในคอลัมน์สำคัญ (เช่น `ราคา` หรือ `จังหวัด` เป็น `NaN`) ระบบจะทำการ**ละทิ้งข้อมูลที่ไม่สมบูรณ์และเริ่มสแครปใหม่**ทันที
- Fast-Forward Check: หากจำนวนแถวใน CSV สะสมเดิมใกล้เคียงกับยอดรวมของระบบ ระบบจะผ่านเข้าสู่ขั้นตอนตรวจสอบและจบงานได้ทันทีโดยไม่ต้องดึงซ้ำ
- **Streaming Auto-Save & Emergency Flush**: ทุกสแครปเปอร์จะทำการบันทึกข้อมูลสะสมลง CSV ทันทีในทุกๆ หน้า และมีระบบ `atexit` Emergency Handler เพื่อการันตีว่าข้อมูลจะไม่สูญหายแม้ผู้ใช้จะสั่งปิดโปรแกรมกะทันหัน

### 3. Master Merge & Parquet Pipeline ([`merge_csv_monthly.py`](merge_csv_monthly.py))
- รวบรวม CSV ของทั้ง 14 ค่าย จัดระเบียบคอลัมน์ให้อยู่ในรูปแบบ **มาตรฐาน 25 คอลัมน์**
- ทำ High-performance Location Normalization ซ้ำอีกรอบด้วย Vectorized Map
- เชื่อมต่อและทำความสะอาดชื่อโครงการผ่าน [`clean_project_util.py`](clean_project_util.py)
- ตัดสตริง `"nan"`, `"None"`, `"null"` ออกทั้งหมด
- บันทึก Master CSV ประจำเดือน (`all_assets_monthly_YYYY_MM.csv`)
- แปลงและอัปเดตไฟล์ความเร็วสูง [`all_assets.parquet`](../all_assets.parquet) และ Parquet แยกวันที่ (`all_assets_YYYY_MM_DD.parquet`) สำหรับแสดงผลบน Streamlit Dashboard ทันที

### 4. LandsMaps Real GPS Coordinate Enrichment (`tools/enrich_led_landsmaps.py`)
- ระบบสกัดพิกัดจริงจากโฉนดที่ดินของกรมบังคับคดี (LED) ที่มี `เลขโฉนด` เชื่อมต่อไปยังระบบค้นหารูปแปลงที่ดิน (LandsMaps)
- จัดเก็บพิกัดจริงลงใน Incremental Parquet Cache (`data/led_coords_cache.parquet`)
- เมื่อรัน [`merge_csv_monthly.py`](merge_csv_monthly.py) ระบบจะดึงพิกัดจริงจากแคชมาเขียนทับพิกัด Centroid อัตโนมัติ

### 5. Cross-Company Deduplication Policy (SAM vs ZmyHome)
- **มาตรการคัดกรองข้อมูลซ้ำซ้อนระดับต้นทาง (Tier 1 Scraper-Level Deduplication)**:
  - ใน [`scrape_zmyhome_monthly.py`](scrape_zmyhome_monthly.py) ฟังก์ชัน `is_sam_property()` จะทำการตรวจจับ Schema `"seller": {"name": "SAM SAM"}` และคีย์เวิร์ด บสส./SAM, "บริหารสินทรัพย์สุขุมวิท", "Sukhumvit Asset Management" ทั้งในชื่อโครงการ หัวข้อประกาศ และโค้ด HTML
  - รายการที่เข้าข่ายจะถูก **ข้าม (Skip)** ตั้งแต่ขั้นตอนการสกัดข้อมูลทันที เพื่อให้ข้อมูลของ SAM มาจากต้นทาง [`scrape_sam_monthly.py`](scrape_sam_monthly.py) เพียงแหล่งเดียวอย่างสมบูรณ์ และป้องกันความคลาดเคลื่อนจากการตัดข้อมูลแปลงข้างเคียง (False Positive) ในระดับการรวมข้อมูล

### 6. Pre-flight Health & Structure Verification ([`preflight_check.py`](preflight_check.py))
- ตรวจสอบ Dependency, ความสมบูรณ์ของ GeoJSON และ Compile Syntax ของสคริปต์ทั้ง 14 ค่ายก่อนเริ่มการสแครปจริงทุกครั้ง
