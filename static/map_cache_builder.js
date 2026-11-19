(function (global) {
  'use strict';

  const GRID_CELL_SIZE = 0.2; // ~22 km grid buckets for instantaneous spatial lookup
  const DEFAULT_CO_RGB = [148, 163, 184];

  const BRAND_TAG_RULES = [
    [/eastgate|อีสท์เกต/i, 'Eastgate / อีสท์เกต'],
    [/ไอดีโอ|ไอดิโอ|ไอเดีย|ideo|ไอดิโอ้|ไอดีโอ้/i, 'IDEO / ไอดิโอ'],
    [/ลุมพ[ิีึื]น[ิีึื]|lumpini|lpn/i, 'LPN / Lumpini'],
    [/พฤกษา|พฤษภา|พฤษา|พึกษา|พฤกสา|pruksa|ps\b/i, 'Pruksa / PS'],
    [/[ศส]ุ[ภพ]าลัย|supalai|spali/i, 'Supalai / ศุภาลัย'],
    [/แสนสิริ|sansiri|siri\b/i, 'Sansiri / แสนสิริ'],
    [/แอสปา[ยร์]+|aspire/i, 'Aspire / แอสปาย'],
    [/ดีคอนโด|dcondo/i, 'Dcondo'],
    [/เดอะ\s*เบส|the\s*base/i, 'The Base'],
    [/ไลฟ์|life\b/i, 'Life'],
    [/ริ[ทธ]ึ่?[มม์]|rhythm/i, 'Rhythm'],
    [/ไนท์บริด[จช์]+|knightsbridge/i, 'Knightsbridge'],
    [/พลัม|plum/i, 'Plum'],
    [/คาซ่า|casa/i, 'Casa'],
    [/เซ็?นทริค|centric/i, 'Centric'],
    [/คอนโดเล็?ต|condolette/i, 'Condolette'],
    [/ยู\s*ดีไลท์|udelight/i, 'U Delight'],
    [/แชปเตอร์\s*วัน|chapter\s*one/i, 'Chapter One'],
    [/รีเจ้?นท์?|regent/i, 'Regent'],
    [/โนเบิล|noble/i, 'Noble'],
    [/พาร์?คแลน[ด์]*|parkland/i, 'Parkland'],
    [/แอชตัน|ashton/i, 'Ashton'],
    [/เอล?ลิโอ|elio/i, 'Elio'],
    [/ยูนิโอ|unio/i, 'Unio'],
    [/โมดิซ|modiz/i, 'Modiz'],
    [/แอทโม[ซส]|atmoz/i, 'Atmoz'],
    [/เคฟ|kave/i, 'Kave'],
    [/แชมเบอร์?ส?|chambers/i, 'Chambers / แชมเบอร์ส'],
    [/เดอะ\s*คิวบ์?|the\s*cube/i, 'The Cube / เดอะคิวบ์'],
    [/พลีโน่?|pleno/i, 'Pleno / พลีโน่'],
    [/บริทาเนีย|britania/i, 'Britania'],
    [/ออริจิ้?น|origin/i, 'Origin / ออริจิ้น'],
    [/ริช\s*พาร์?ค|rich\s*park/i, 'Rich Park / ริชพาร์ค'],
    [/เดอะ\s*ทรี|the\s*tree/i, 'The Tree / เดอะทรี'],
    [/เมโทร\s*ลักซ์?|metro\s*luxe/i, 'Metro Luxe / เมโทรลักซ์'],
    [/เดอะ\s*ทรัสต์?|the\s*trust/i, 'The Trust / เดอะทรัสต์'],
    [/ชวนชื่?น|chuanchuen/i, 'Chuan Chuen / ชวนชื่น'],
    [/เพอร์เฟ[็คกต์]+|perfect/i, 'Perfect / เพอร์เฟค'],
    [/[ภพ]ัสสร|passorn/i, 'Passorn / ภัสสร'],
    [/มั?ณฑนา|mantana/i, 'Mantana / มัณฑนา'],
    [/ชัยพฤก[ษ์ษา]+|chaiyapruek/i, 'Chaiyapruek / ชัยพฤกษ์'],
    [/วิลลาจจิ?โอ|villaggio/i, 'Villaggio / วิลลาจจิโอ'],
    [/อินดี้?|indy\b/i, 'Indy / อินดี้']
  ];

  function getBrandSearchTag(name) {
    if (!name) return '';
    const str = name.toString();
    for (let i = 0; i < BRAND_TAG_RULES.length; i++) {
      if (BRAND_TAG_RULES[i][0].test(str)) {
        return BRAND_TAG_RULES[i][1];
      }
    }
    return '';
  }

  function isInvalidProjectName(p) {
    if (!p) return true;
    let s = p.toString().trim();
    s = s.replace(/^['"“‘\s]+|['"”’\s]+$/g, '');
    if (
      !s ||
      s === '-' ||
      s === 'ไม่มีข้อมูล' ||
      s === 'ไม่มีชื่อ' ||
      s === 'ไม่ระบุ' ||
      s === 'null' ||
      s === 'undefined' ||
      s === 'โครงการไม่มีชื่อ' ||
      s === 'ไม่มี' ||
      s === 'โครงการ' ||
      s === 'หมู่บ้าน' ||
      s === 'คอนโด'
    ) {
      return true;
    }
    if (s.length <= 1) return true;
    if (/^-?\d{1,2}\.\d+[\s,]+-?\d{2,3}\.\d+$/.test(s)) return true;
    if (/^[\d.,/\s-]+$/.test(s)) return true;
    if (/^(บ้านเดี่ยว|บ้านแฝด|บ้าน|ทาวน์โฮม|ทาวน์เฮ้าส์|คอนโด|ห้องชุด|ที่ดิน|อาคารพาณิชย์|ตึกแถว)\s*\d+$/i.test(s)) return true;
    if (/^(?:บ้านเดี่ยว|บ้านแฝด|บ้านตึก|บ้านไม้|บ้านครึ่งตึกครึ่งไม้|บ้าน|ทาวน์เฮ้าส์|ทาวน์โฮม|ทาวเฮ้าส์|ทาวน์ฮ้าส์|ตึกแถว|อาคารพาณิชย์|อาคารโกดัง|วิลล่า|คอนโด)?\s*\d+(?:\.\d+)?\s*ชั้น\b/i.test(s)) return true;
    if (/^\d{5}\s*(?:บ้าน|ทาวน์|อาคาร|ที่ดิน|คอนโด|เดอะ|มบ\.|หมู่บ้าน|ทาวเฮ้าส์)/i.test(s)) return true;
    if (/^\d+[\d.,/-]*\s*(?:ตร\.?ว|ตร\.?ม|ตารางวา|ตารางเมตร|ไร่|วา)\b/i.test(s)) return true;
    if (/^(ใกล้|ติด)\s*(bts|mrt|แอร์พอร์ต|ทางด่วน|ถนน|สถานี|ห้าง)\b/i.test(s)) return true;
    if (/^\d+\s*ห้อง(นอน)?\s*$/i.test(s) || /^(สตูดิโอ|studio)\s*$/i.test(s) || /^\d+\s*bed(room)?s?\s*$/i.test(s)) return true;
    if (/(?:\d+\s*(?:ห้องนอน|ห้องน้ำ)|\d+\s*นอน\s*\d+\s*น้ำ|ห้อง(?:นอน|น้ำ)?\s*\d+\s*ห้อง)/i.test(s)) return true;
    if (/^(?:ขาย|เช่า|เซ้ง|ให้เช่า|ขายด่วน|ขายถูก|ด่วน|ต้องการขาย|ลดราคา|ขายบ้าน|ขายคอนโด)\b/i.test(s)) return true;
    if (/ขาย(?:คอนโด|บ้าน|ทาวน์|ที่ดิน)/i.test(s)) return true;
    if (/(?:ราคา|ขายเพียง|ลดเหลือ|ผ่อนเพียง|ตรว\.ละ|วาละ|ขาย|เช่า)\s*\d+(?:\.\d+)?\s*(?:ลบ|ล้าน|แสน|บาท|บ\b)/i.test(s)) return true;
    if (/(?:ขายด่วน|ด่วนมาก|ลดกระหน่ำ|ขายถูกที่สุด|ราคาถูกที่สุด|รีโนเวทใหม่|รีโนเวทแล้ว|ตกแต่งใหม่ทั้งหลัง|พร้อมอยู่ทันที|กู้เต็ม|กู้ได้เต็ม|ฟรีโอน|ขายขาดทุน|เจ้าของขายเอง|ผ่อนตรง|รับผ่อนตรง|agent welcomed|ขายยกแปลง)/i.test(s)) return true;
    if (/(?:โทร|tel|contact|line\s*id)\s*[:\.]?\s*\d/i.test(s)) return true;
    if (/\d+[\d.,]*\s*(?:ตร\.?ว|ตร\.?ม|ตารางวา|ตารางเมตร)\b/i.test(s) && s.length > 15) return true;
    if (/ใน(?:อำเภอ|อ\.)\s*[ก-๙]+/i.test(s) && /ราคา/i.test(s)) return true;
    if (/(?:พร้อมอยู่|ตกแต่งครบ|เฟอร์นิเจอร์|ฟรีโอน|วิวสวย|วิวทะเล|วิวสระ|ทำเลทอง)/i.test(s) && s.length > 20) return true;
    return false;
  }

  function cleanDisplayProjectName(name) {
    if (!name) return '';
    let txt = name.toString().trim();
    txt = txt.replace(/^['"“‘\s]+|['"”’\s]+$/g, '');
    if (txt.includes(' : ')) {
      const parts = txt.split(' : ');
      txt = parts.length > 1 ? parts[1] : parts[0];
    }
    txt = txt
      .replace(/ลุมพินี\s*ทาวน์ชิป\s*รังสิต/gi, 'ลุมพินี ทาวน์ชิป รังสิต')
      .replace(/ทางน์ชิป|ทาวชิป|ทาวน์ซิป|ทาวนชิป/gi, 'ทาวน์ชิป')
      .replace(/township\b/gi, 'ทาวน์ชิป')
      .replace(/c[\s,\.]*d[\s,\.]*e\b/gi, 'ซีดีอี')
      .replace(/a[\s,\.]*b\b/gi, 'เอบี')
      .replace(/c[\s,\.]*d\b/gi, 'ซีดี')
      .replace(/e[\s,\.]*f\b/gi, 'อีเอฟ')
      .replace(/f[\s,\.]*g\b/gi, 'เอฟจี');

    txt = txt
      .replace(/เดอะ\s*คิว(?:บ์|บ)/gi, 'เดอะคิวบ์')
      .replace(/เดอะ\s*คอนเน[คกต์]+/gi, 'เดอะ คอนเนค')
      .replace(/เดอะ\s*เบส/gi, 'เดอะเบส')
      .replace(/เดอะ\s*ทรี/gi, 'เดอะทรี')
      .replace(/เดอะ\s*ทรัสต์?/gi, 'เดอะทรัสต์')
      .replace(/รีเจ้?น[ท์]*/gi, 'รีเจ้นท์')
      .replace(/ไอดีโอ้?|ไอดิโอ้?|ไอเดีย/gi, 'ไอดีโอ')
      .replace(/พฤกษ์?ลดา/gi, 'พฤกษ์ลดา')
      .replace(/มั?ณฑนา/gi, 'มัณฑนา')
      .replace(/ชัยพฤก[ษ์ษา]+/gi, 'ชัยพฤกษ์')
      .replace(/เพอร์?เฟ[็คกต์]+/gi, 'เพอร์เฟค')
      .replace(/วิลลาจจิ?โอ/gi, 'วิลลาจจิโอ')
      .replace(/อินดี้?/gi, 'อินดี้');

    txt = txt
      .replace(/([ก-๙a-zA-Z])\s*,\s*([ก-๙a-zA-Z])\s*,\s*([ก-๙a-zA-Z])/g, '$1$2$3')
      .replace(/([ก-๙a-zA-Z])\s*,\s*([ก-๙a-zA-Z])/g, '$1$2')
      .replace(/([ก-๙a-zA-Z])\s*\.\s*([ก-๙a-zA-Z])\s*\.\s*([ก-๙a-zA-Z])/g, '$1$2$3')
      .replace(/([ก-๙a-zA-Z])\s*\.\s*([ก-๙a-zA-Z])/g, '$1$2')
      .replace(/\s*-\s*/g, '-')
      .replace(/คลอง\s*(\d+)/g, 'คลอง $1')
      .replace(/\s+/g, ' ')
      .trim();
    return txt;
  }

  function normalizeProjectKeyword(str) {
    if (!str) return '';
    let txt = str.toString().trim().toLowerCase();
    txt = txt.replace(/^['"“‘\s]+|['"”’\s]+$/g, '');
    if (txt.includes(' : ')) {
      const parts = txt.split(' : ');
      txt = parts.length > 1 ? parts[1] : parts[0];
    }
    txt = txt.replace(
      /^(คอนโด\s*โครงการ|โครงการ\s*คอนโด|โครงการ\s*หมู่บ้าน|อาคารชุด|คอนโดมิเนียม|มีเนียม|โครงการ|หมู่บ้าน|คอนโด|บ้านเดี่ยว|บ้านแฝด|บ้าน|ทาวน์โฮม|ทาวน์เฮ้าส์|ขายคอนโด)\s*/gi,
      ''
    );
    txt = txt.replace(
      /(\[.*?\]|\(.*?\)|\[[^\]]*$|\([^)]*$|,\s*(กรุงเทพมหานคร|กรุงเทพฯ|กรุงเทพ|นนทบุรี|ปทุมธานี|สมุทรปราการ|ชลบุรี|เชียงใหม่|ระยอง|ภูเก็ต).*$|[\s\-_/]+(?:อาคาร|ตึก)\s+[a-zA-Z0-9ก-๙]\s+ชั้น\s*\d+.*$|[\s\-_/]+ชั้น\s*\d+.*$|ชั้น\s*\d+.*$|\b(ติด|ใกล้)\s*(bts|mrt).*$)/gi,
      ''
    );

    txt = txt
      .replace(/คลอง\s*(\d+)/g, 'คลอง$1')
      .replace(/เฟส\s*(\d+)/g, 'เฟส$1')
      .replace(/ซอย\s*(\d+)/g, 'ซอย$1')
      .replace(/สาย\s*(\d+)/g, 'สาย$1')
      .replace(/phase\s*(\d+)/gi, 'เฟส$1');

    txt = txt
      .replace(/sukhumvit|สุขุมวิท/gi, 'สุขุมวิท')
      .replace(/rama|พระราม/gi, 'พระราม')
      .replace(/sathorn|sathon|สาทร/gi, 'สาทร')
      .replace(/asoke|asok|อโศก/gi, 'อโศก')
      .replace(/ladprao|latphrao|ลาดพร้าว/gi, 'ลาดพร้าว')
      .replace(/tiwanon|ติวานนท์/gi, 'ติวานนท์')
      .replace(/bangna|bang\s*na|บางนา/gi, 'บางนา')
      .replace(/ratchada|รัชดา/gi, 'รัชดา')
      .replace(/thonglor|ทองหล่อ/gi, 'ทองหล่อ')
      .replace(/ekkamai|เอกมัย/gi, 'เอกมัย')
      .replace(/silom|สีลม/gi, 'สีลม')
      .replace(/rangsit|รังสิต/gi, 'รังสิต')
      .replace(/klong/gi, 'คลอง')
      .replace(/mobi|โมบิ/gi, 'โมบิ')
      .replace(/ville|วิลล์/gi, 'วิลล์')
      .replace(/park\b|พาร์ค|ปาร์ค/gi, 'พาร์ค')
      .replace(/place|เพลส/gi, 'เพลส')
      .replace(/prime|ไพร์ม/gi, 'ไพร์ม')
      .replace(/veranda|เวอเรนด้า/gi, 'เวอเรนด้า')
      .replace(/campus|แคมปัส/gi, 'แคมปัส')
      .replace(/resort|รีสอร์ท/gi, 'รีสอร์ท')
      .replace(/station|สเตชั่น/gi, 'สเตชั่น')
      .replace(/condo\b/gi, 'คอนโด')
      .replace(/ทางน์ชิป|ทาวชิป|ทาวน์ซิป|ทาวนชิป|township/gi, 'ทาวน์ชิป')
      .replace(/ซี[,\.\s]*ดี[,\.\s]*อี|c[\s,\.]*d[\s,\.]*e/gi, 'ซีดีอี')
      .replace(/เอ[,\.\s]*บี|a[\s,\.]*b/gi, 'เอบี')
      .replace(/ซี[,\.\s]*ดี|c[\s,\.]*d/gi, 'ซีดี')
      .replace(/อี[,\.\s]*เอฟ|e[\s,\.]*f/gi, 'อีเอฟ')
      .replace(/เอฟ[,\.\s]*จี|f[\s,\.]*g/gi, 'เอฟจี')
      .replace(/ซี[,\.\s]*ดี[,\.\s]*อี[,\.\s]*เอฟ|c[\s,\.]*d[\s,\.]*e[\s,\.]*f/gi, 'ซีดีอีเอฟ')
      .replace(/บี[.\s]*เค[.\s]*|b[\s\.]*k[\s\.]*/gi, 'บีเค')
      .replace(/เอส[.\s]*ซี[.\s]*|s[\s\.]*c[\s\.]*/gi, 'เอสซี')
      .replace(/สินมั่?นคง/gi, 'สินมั่นคง')
      .replace(/eastgate/gi, 'อีสท์เกต')
      .replace(/ไอดีโอ้?|ไอดิโอ้?|ไอเดีย|ideo|idio/gi, 'ไอดีโอ')
      .replace(/ลุมพ[ิีึื]น[ิีึื]|lumpini|lpn\b/gi, 'ลุมพินี')
      .replace(/พฤกษา|พฤษภา|พฤษา|พึกษา|พฤกสา|พฤษษา|พฤกษภ|pruksa|ps\b/gi, 'พฤกษา')
      .replace(/[ศส]ุ[ภพ]าลัย|supalai|spali\b/gi, 'ศุภาลัย')
      .replace(/แสนสิริ|sansiri|siri\b/gi, 'แสนสิริ')
      .replace(/แอสปา[ยร์]+|aspire/gi, 'แอสปาย')
      .replace(/ดีคอนโด|dcondo|d\s*condo/gi, 'ดีคอนโด')
      .replace(/เดอะ\s*เบส|the\s*base/gi, 'เดอะเบส')
      .replace(/ไลฟ์|life\b/gi, 'ไลฟ์')
      .replace(/ริ[ทธ]ึ่?[มม์]|rhythm/gi, 'ริทึ่ม')
      .replace(/ไนท์บริด[จช์]*|knightsbridge/gi, 'ไนท์บริดจ์')
      .replace(/พลัม|plum\b/gi, 'พลัม')
      .replace(/คาซ[่า]|casa\b/gi, 'คาซ่า')
      .replace(/เซ็?นทริ[คก]|centric/gi, 'เซ็นทริค')
      .replace(/คอนโดเล็?ต|condolette/gi, 'คอนโดเลต')
      .replace(/ยู\s*ดีไลท์|u\s*delight/gi, 'ยูดีไลท์')
      .replace(/แชปเตอร์\s*วัน|chapter\s*one/gi, 'แชปเตอร์วัน')
      .replace(/รีเจ้?น[ท์]*|regent/gi, 'รีเจ้นท์')
      .replace(/โนเบิ?ล|noble/gi, 'โนเบิล')
      .replace(/พาร์?คแลน[ด์]*|parkland/gi, 'พาร์คแลนด์')
      .replace(/แอชตัน|ashton/gi, 'แอชตัน')
      .replace(/เอล?ลิโอ|elio/gi, 'เอลิโอ')
      .replace(/ยูนิโอ|unio/gi, 'ยูนิโอ')
      .replace(/โมดิ[ซสช]|modiz/gi, 'โมดิซ')
      .replace(/แอทโม[ซส]|atmoz/gi, 'แอทโมซ')
      .replace(/เคฟ|kave/gi, 'เคฟ')
      .replace(/แชมเบอร์?ส?|chambers/gi, 'แชมเบอร์ส')
      .replace(/เดอะ\s*คิว(?:บ์|บ)?|the\s*cube/gi, 'เดอะคิวบ์')
      .replace(/พลีโน่?|pleno/gi, 'พลีโน่')
      .replace(/บริทาเนีย|britani?a/gi, 'บริทาเนีย')
      .replace(/ออริจิ้?น|origin/gi, 'ออริจิ้น')
      .replace(/ริช\s*พาร์?ค|rich\s*park/gi, 'ริชพาร์ค')
      .replace(/เดอะ\s*ทรี|the\s*tree/gi, 'เดอะทรี')
      .replace(/เมโทร\s*ลักซ์?|metro\s*luxe/gi, 'เมโทรลักซ์')
      .replace(/เดอะ\s*ทรัสต์?|the\s*trust/gi, 'เดอะทรัสต์')
      .replace(/ชวนชื่?น|chuanchuen|chuan\s*chuen/gi, 'ชวนชื่น')
      .replace(/เพอร์?เฟ[็คกต์]+|perfect/gi, 'เพอร์เฟค')
      .replace(/[ภพ]ัสสร|passorn/gi, 'ภัสสร')
      .replace(/มั?ณฑนา|mantana/gi, 'มัณฑนา')
      .replace(/ชัยพฤก[ษ์ษา]+|chaiyapruek/gi, 'ชัยพฤกษ์')
      .replace(/วิลลาจจิ?โอ|villaggio/gi, 'วิลลาจจิโอ')
      .replace(/อินดี้?|indy\b/gi, 'อินดี้')
      .replace(/ฮาบิเทีย|habitia/gi, 'ฮาบิเทีย')
      .replace(/ส[ะา]ราญสิริ|saransiri/gi, 'สราญสิริ')
      .replace(/บุราสิริ|burasiri/gi, 'บุราสิริ')
      .replace(/[เศส]รษฐสิริ|setthasiri/gi, 'เศรษฐสิริ')
      .replace(/นาราสิริ|narasiri/gi, 'นาราสิริ')
      .replace(/คณาสิริ|kanasiri/gi, 'คณาสิริ')
      .replace(/อณาสิริ|anasiri/gi, 'อณาสิริ')
      .replace(/เซ็?นโทร|centro/gi, 'เซนโทร')
      .replace(/บ้านกลางเมือง|baan\s*klang\s*muang/gi, 'บ้านกลางเมือง')
      .replace(/บ้านกลางกรุง|baan\s*klang\s*krung/gi, 'บ้านกลางกรุง')
      .replace(/ซิตี้เซนส์?|city\s*sense/gi, 'ซิตี้เซนส์')
      .replace(/เดอะ\s*คอนเน[คกต์]+|the\s*connect/gi, 'เดอะ คอนเนค')
      .replace(/พฤกษาวิลล์?|pruksa\s*ville/gi, 'พฤกษาวิลล์')
      .replace(/บ้านพฤกษา|baan\s*pruksa/gi, 'บ้านพฤกษา')
      .replace(/เดอะ\s*ซิตี้|the\s*city/gi, 'เดอะ ซิตี้')
      .replace(/เดอะ\s*ไลน์|the\s*line/gi, 'เดอะ ไลน์')
      .replace(/ทิพมา[ศส]/gi, 'ทิพมาศ')
      .replace(/คาร์พ[ิี]เดี้ย?ม/gi, 'คาร์พิเดียม')
      .replace(/เดอะ\s*คันทรี?่?|the\s*country/gi, 'เดอะคันทรี')
      .replace(/โมเดิร?์?น|modern/gi, 'โมเดิร์น')
      .replace(/โฮม|home\b/gi, 'โฮม')
      .replace(/เบญจทรัพย์/gi, 'เบญจทรัพย์')
      .replace(/แพรมาพร/gi, 'แพรมาพร')
      .replace(/ทรัพย์รุ่งเรือง/gi, 'ทรัพย์รุ่งเรือง')
      .replace(/แบงค์?\s*คอก\s*ฮอไรซอน|bangkok\s*horizon/gi, 'แบงค์คอก ฮอไรซอน')
      .replace(/พฤกษ์?ลดา|prueklada/gi, 'พฤกษ์ลดา')
      .replace(/กัสโต้|gusto/gi, 'กัสโต้')
      .replace(/ควอลิตี้\s*เฮ้าส์|quality\s*house|q\.?\s*house/gi, 'ควอลิตี้ เฮ้าส์')
      .replace(/แลนด์\s*แอนด์?\s*เฮ้าส์?|land\s*(&|and)\s*house/gi, 'แลนด์ แอนด์ เฮ้าส์')
      .replace(/อีสท์เกต|eastgate/gi, 'อีสท์เกต');

    txt = txt.replace(/[\s\-_/.,:;()\[\]{}]+/g, '');
    txt = txt.replace(/[่้๊๋์็]/g, '');
    txt = txt.replace(/[ศษ]/g, 'ส').replace(/ภ/g, 'พ').replace(/ธ/g, 'ท');
    txt = txt.replace(/ณ/g, 'น').replace(/ญ/g, 'ย').replace(/ฌ/g, 'ช').replace(/ฬ/g, 'ล');
    txt = txt.replace(/[ีืึ]/g, 'ิ');

    if (['บ้าน', 'คอนโด', 'ที่ดิน', 'ทาวน์โฮม', 'อาคารพาณิชย์'].includes(txt)) return '';
    return txt;
  }

  /**
   * Native GZIP base64 decompression using fetch('data:...') for C++ base64 decoding,
   * with fallback to atob loop when data URL fetch is restricted.
   */
  async function decompressGzip(b64str) {
    if (!b64str) return '';
    try {
      const resp = await fetch('data:application/octet-stream;base64,' + b64str);
      if (resp && resp.body) {
        const ds = new DecompressionStream('gzip');
        return await new Response(resp.body.pipeThrough(ds)).text();
      }
    } catch (_e) {
      // Fallback below
    }
    const raw = atob(b64str);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    const ds = new DecompressionStream('gzip');
    const writer = ds.writable.getWriter();
    writer.write(bytes);
    writer.close();
    return await new Response(ds.readable).text();
  }

  function formatThbPriceStr(priceVal) {
    if (!(priceVal > 0)) return 'ไม่ระบุ';
    const s = String(Math.round(priceVal));
    let out = '';
    for (let i = s.length; i > 0; i -= 3) {
      out = s.slice(Math.max(0, i - 3), i) + (out ? ',' + out : '');
    }
    return '฿' + out + ' บาท';
  }

  function hydrateMapRows(data, lut) {
    if (!data || !data.length) return data;
    const _lut = lut || {};
    const coRgbLut = _lut.co_rgb;
    const coLut = _lut.co;
    const tyLut = _lut.ty;
    const pvLut = _lut.pv;
    const stLut = _lut.st;
    const rgLut = _lut.rg;
    const dtLut = _lut.dt;
    const subdtLut = _lut.subdt;
    const prjLut = _lut.prj;
    const plaintiffLut = _lut.plaintiff;

    for (let i = 0; i < data.length; i++) {
      const d = data[i];
      d._uid = i;
      d.lon = +d.lon;
      d.lat = +d.lat;

      const ci = +d._ci;
      if (d.r !== undefined && d.g !== undefined && d.b !== undefined && d.r !== '') {
        d.r = +d.r;
        d.g = +d.g;
        d.b = +d.b;
      } else {
        const rgb = (coRgbLut && coRgbLut[ci]) || DEFAULT_CO_RGB;
        d.r = rgb[0];
        d.g = rgb[1];
        d.b = rgb[2];
      }

      d._company = (coLut && coLut[ci]) || '-';
      d._type = (tyLut && tyLut[+d._ti]) || '-';
      d._prov = (pvLut && pvLut[+d._pi]) || '-';
      d._sale = (stLut && stLut[+d._sti]) || '-';
      d._region = (rgLut && rgLut[+d._rgi]) || '-';
      d._district = (dtLut && dtLut[+d._dti]) || '-';
      d._subdistrict = (subdtLut && d._subdti !== undefined && subdtLut[+d._subdti]) || '-';
      d._project = (prjLut && d._prji !== undefined && prjLut[+d._prji]) || '-';
      d._price = +d._p || 0;
      if (!d._price_str) {
        d._price_str = formatThbPriceStr(d._price);
      }
      d._unit_price = +d._up || 0;
      d._sqw = +d._sqw || 0;
      d._sqm = +d._sqm || 0;
      d._puw = +d._puw || 0;
      d._pum = +d._pum || 0;
      d._fl = d._fl !== undefined ? +d._fl : -1;
      d._bed = d._bed !== undefined ? +d._bed : -1;
      d._bath = d._bath !== undefined ? +d._bath : -1;
      d._pkg = d._pkg !== undefined ? +d._pkg : -1;
      d._age = d._age !== undefined ? +d._age : -1;
      d._sold_p = d._sold_p !== undefined ? +d._sold_p : 0;
      d._sold_date = d._sold_date || '';
      d._plaintiff = (plaintiffLut && d._pti !== undefined && plaintiffLut[+d._pti]) || '';
    }
    return data;
  }

  function buildSpatialGrid(data) {
    const grid = new Map();
    if (!data || !data.length) return grid;
    for (let i = 0; i < data.length; i++) {
      const d = data[i];
      if (isNaN(d.lon) || isNaN(d.lat)) continue;
      const gx = Math.floor(d.lon / GRID_CELL_SIZE);
      const gy = Math.floor(d.lat / GRID_CELL_SIZE);
      const key = gx + '_' + gy;
      let cell = grid.get(key);
      if (!cell) {
        cell = [];
        grid.set(key, cell);
      }
      cell.push(d);
    }
    return grid;
  }

  function _indexProjectItemCo(nk, p, d, globalNormToItemsMap, globalProjToItemsMap, globalNormToCompaniesMap, globalProjToCompaniesMap, projCompanyCountsMap) {
    let nArr = globalNormToItemsMap.get(nk);
    if (!nArr) {
      nArr = [];
      globalNormToItemsMap.set(nk, nArr);
    }
    nArr.push(d);

    let pArr = globalProjToItemsMap.get(p);
    if (!pArr) {
      pArr = [];
      globalProjToItemsMap.set(p, pArr);
    }
    pArr.push(d);

    const co = (d._company || '').trim();
    if (co && co !== '-') {
      let coSet = globalNormToCompaniesMap.get(nk);
      if (!coSet) {
        coSet = new Set();
        globalNormToCompaniesMap.set(nk, coSet);
      }
      coSet.add(co);

      let pCoSet = globalProjToCompaniesMap.get(p);
      if (!pCoSet) {
        pCoSet = new Set();
        globalProjToCompaniesMap.set(p, pCoSet);
      }
      pCoSet.add(co);

      let counts = projCompanyCountsMap.get(nk);
      if (!counts) {
        counts = {};
        projCompanyCountsMap.set(nk, counts);
      }
      counts[co] = (counts[co] || 0) + 1;
    }
  }

  function buildProjectIndex(data, lut) {
    const samProjectStatsMap = new Map();
    const globalProjToNormMap = new Map();
    const globalNormToItemsMap = new Map();
    const globalProjToItemsMap = new Map();
    const globalNormToCompaniesMap = new Map();
    const globalProjToCompaniesMap = new Map();
    const projCompanyCountsMap = new Map();
    const normKeyToCanonicalMap = new Map();
    let allSamProjectsList = [];
    let allOtherProjectsList = [];
    let allProjectsList = [];

    const lutObj = lut && typeof lut === 'object' && !Array.isArray(lut) ? lut : null;
    const rawSamPrj = (lutObj && lutObj.sam_prj) || (Array.isArray(lut) ? lut : null);
    const rawOtherPrj = (lutObj && lutObj.other_prj) || null;
    const rawAllPrj = (lutObj && lutObj.all_prj) || null;
    const prjStatsDict = (lutObj && lutObj.prj_stats) || {};

    // Fast path: pre-computed structured project inventory from backend lookup
    if (rawSamPrj && Array.isArray(rawSamPrj) && rawSamPrj.length > 0) {
      allSamProjectsList = rawSamPrj.filter(p => p && p !== '-' && p !== 'ไม่มีข้อมูล' && p !== 'ไม่ระบุ' && p.length > 1);
      allOtherProjectsList =
        rawOtherPrj && Array.isArray(rawOtherPrj)
          ? rawOtherPrj.filter(p => p && p !== '-' && p !== 'ไม่มีข้อมูล' && p !== 'ไม่ระบุ' && p.length > 1)
          : [];
      allProjectsList =
        rawAllPrj && Array.isArray(rawAllPrj) && rawAllPrj.length > 0
          ? rawAllPrj.filter(p => p && p !== '-' && p !== 'ไม่มีข้อมูล' && p !== 'ไม่ระบุ' && p.length > 1)
          : allSamProjectsList.concat(allOtherProjectsList);

      for (let i = 0; i < allSamProjectsList.length; i++) {
        const p = allSamProjectsList[i];
        const pair = prjStatsDict[p] || [1, 0];
        const sc = Math.max(1, pair[0] || 1);
        const oc = pair[1] || 0;
        const nk = normalizeProjectKeyword(p);
        const tag = getBrandSearchTag(p);
        samProjectStatsMap.set(p, { sam: sc, other: oc, normKey: nk, tag: tag });
        if (nk) normKeyToCanonicalMap.set(nk, p);
      }

      for (let i = 0; i < allOtherProjectsList.length; i++) {
        const p = allOtherProjectsList[i];
        const pair = prjStatsDict[p] || [0, 1];
        const oc = Math.max(1, pair[1] || 1);
        const nk = normalizeProjectKeyword(p);
        const tag = getBrandSearchTag(p);
        samProjectStatsMap.set(p, { sam: 0, other: oc, normKey: nk, tag: tag });
        if (nk) normKeyToCanonicalMap.set(nk, p);
      }

      if (data && data.length > 0) {
        for (let i = 0; i < data.length; i++) {
          const d = data[i];
          const p = (d._project || '').trim();
          if (!p || p === '-' || p === 'ไม่มีข้อมูล' || p.length <= 1) continue;
          let nk = globalProjToNormMap.get(p);
          if (nk === undefined) {
            nk = normalizeProjectKeyword(p);
            globalProjToNormMap.set(p, nk);
          }
          d._normKey = nk;
          _indexProjectItemCo(
            nk,
            p,
            d,
            globalNormToItemsMap,
            globalProjToItemsMap,
            globalNormToCompaniesMap,
            globalProjToCompaniesMap,
            projCompanyCountsMap
          );
        }
      }

      return {
        allSamProjectsList,
        allOtherProjectsList,
        allProjectsList,
        samProjectStatsMap,
        globalProjToNormMap,
        globalNormToItemsMap,
        globalProjToItemsMap,
        globalNormToCompaniesMap,
        globalProjToCompaniesMap,
        projCompanyCountsMap,
        normKeyToCanonicalMap
      };
    }

    // Fallback when structured project metadata isn't present
    if (data && data.length > 0) {
      const samCountsByNorm = new Map();
      const otherCountsByNorm = new Map();
      const normKeyGroups = new Map();

      for (let i = 0; i < data.length; i++) {
        const d = data[i];
        const p = (d._project || '').trim();
        const isSam = (d._company || '').toString().trim().toUpperCase() === 'SAM';
        if (!isSam && isInvalidProjectName(p)) {
          d._normKey = '';
          continue;
        }
        if (isSam && (!p || p === '-' || p === 'ไม่มีข้อมูล' || p === 'ไม่ระบุ' || p === 'null' || p === 'undefined' || p.length <= 1)) {
          d._normKey = '';
          continue;
        }
        let nk = globalProjToNormMap.get(p);
        if (nk === undefined) {
          nk = normalizeProjectKeyword(p);
          globalProjToNormMap.set(p, nk);
        }
        d._normKey = nk;
        if (!nk || nk.length <= 1) continue;

        if (isSam) {
          samCountsByNorm.set(nk, (samCountsByNorm.get(nk) || 0) + 1);
        } else {
          otherCountsByNorm.set(nk, (otherCountsByNorm.get(nk) || 0) + 1);
        }

        _indexProjectItemCo(
          nk,
          p,
          d,
          globalNormToItemsMap,
          globalProjToItemsMap,
          globalNormToCompaniesMap,
          globalProjToCompaniesMap,
          projCompanyCountsMap
        );

        let grp = normKeyGroups.get(nk);
        if (!grp) {
          grp = { samRaws: new Map(), otherRaws: new Map() };
          normKeyGroups.set(nk, grp);
        }
        const targetMap = isSam ? grp.samRaws : grp.otherRaws;
        targetMap.set(p, (targetMap.get(p) || 0) + 1);
      }

      const samProjectsList = [];
      const otherProjectsList = [];
      const seenCanonicalNames = new Set();

      normKeyGroups.forEach((grp, nk) => {
        let bestRaw = '';
        let bestCount = -1;
        if (grp.samRaws.size > 0) {
          grp.samRaws.forEach((cnt, raw) => {
            if (cnt > bestCount) {
              bestCount = cnt;
              bestRaw = raw;
            }
          });
        } else {
          grp.otherRaws.forEach((cnt, raw) => {
            if (cnt > bestCount) {
              bestCount = cnt;
              bestRaw = raw;
            }
          });
        }

        const canonicalName = cleanDisplayProjectName(bestRaw);
        if (!canonicalName || seenCanonicalNames.has(canonicalName)) return;
        seenCanonicalNames.add(canonicalName);

        const sc = samCountsByNorm.get(nk) || 0;
        const oc = otherCountsByNorm.get(nk) || 0;
        const tag = getBrandSearchTag(canonicalName);

        samProjectStatsMap.set(canonicalName, { sam: sc, other: oc, normKey: nk, tag: tag });
        normKeyToCanonicalMap.set(nk, canonicalName);

        if (sc > 0) {
          samProjectsList.push(canonicalName);
        } else {
          otherProjectsList.push(canonicalName);
        }
      });

      samProjectsList.sort((a, b) => {
        const statsA = samProjectStatsMap.get(a) || { sam: 0, other: 0 };
        const statsB = samProjectStatsMap.get(b) || { sam: 0, other: 0 };
        const hasCompA = statsA.other > 0 ? 1 : 0;
        const hasCompB = statsB.other > 0 ? 1 : 0;
        if (hasCompA !== hasCompB) return hasCompB - hasCompA;
        if (statsA.other !== statsB.other) return statsB.other - statsA.other;
        if (statsA.sam !== statsB.sam) return statsB.sam - statsA.sam;
        return a.localeCompare(b, 'th');
      });

      otherProjectsList.sort((a, b) => {
        const statsA = samProjectStatsMap.get(a) || { sam: 0, other: 0 };
        const statsB = samProjectStatsMap.get(b) || { sam: 0, other: 0 };
        if (statsA.other !== statsB.other) return statsB.other - statsA.other;
        return a.localeCompare(b, 'th');
      });

      allSamProjectsList = samProjectsList.slice();
      allOtherProjectsList = otherProjectsList.slice();
      allProjectsList = samProjectsList.concat(otherProjectsList);
    }

    return {
      allSamProjectsList,
      allOtherProjectsList,
      allProjectsList,
      samProjectStatsMap,
      globalProjToNormMap,
      globalNormToItemsMap,
      globalProjToItemsMap,
      globalNormToCompaniesMap,
      globalProjToCompaniesMap,
      projCompanyCountsMap,
      normKeyToCanonicalMap
    };
  }

  function computeTypeCounts(data) {
    const typeCounts = {};
    if (data && data.length > 0) {
      for (let i = 0; i < data.length; i++) {
        const t = (data[i]._type || '').trim();
        if (t && t !== '-') {
          typeCounts[t] = (typeCounts[t] || 0) + 1;
        }
      }
    }
    return typeCounts;
  }

  function getParentHost() {
    try {
      if (global.parent && global.parent !== global) return global.parent;
    } catch (_e) {
      // Ignore cross-origin frame access error
    }
    return null;
  }

  function getValidParentCache(expectedMtime) {
    const host = getParentHost();
    if (!host || !host.__NOVA_MAP_CACHE__) return null;
    const c = host.__NOVA_MAP_CACHE__;
    if (!c.data || !c.data.length || !c.spatialGrid || !c.projIndex) return null;
    if (expectedMtime && String(c.mtime || '') !== String(expectedMtime)) return null;
    return c;
  }

  function getParentBoundaryCache() {
    const host = getParentHost();
    return host && host.__NOVA_BOUNDARY_CACHE__ ? host.__NOVA_BOUNDARY_CACHE__ : null;
  }

  function storeParentBoundaryCache(kind, dictObj) {
    if (!dictObj || typeof dictObj !== 'object' || Object.keys(dictObj).length === 0) return;
    const host = getParentHost();
    if (!host) return;
    if (!host.__NOVA_BOUNDARY_CACHE__) host.__NOVA_BOUNDARY_CACHE__ = {};
    host.__NOVA_BOUNDARY_CACHE__[kind] = dictObj;
  }

  async function yieldIfVisible() {
    if (typeof document !== 'undefined' && document.hidden) return;
    await new Promise(resolve => setTimeout(resolve, 0));
  }

  async function buildAndStoreParentCache(mtimeToken, rawPayload, onProgress) {
    const mtimeStr = mtimeToken ? String(mtimeToken) : '';
    const existing = getValidParentCache(mtimeStr);
    if (existing) {
      if (typeof onProgress === 'function') onProgress(100, '✓ พร้อมใช้งานแล้ว');
      return existing;
    }

    const lutB64 = rawPayload && rawPayload.lut ? rawPayload.lut : '';
    const csvB64 = rawPayload && rawPayload.csv ? rawPayload.csv : '';
    if (!csvB64) {
      throw new Error('Missing map CSV payload');
    }

    if (typeof onProgress === 'function') {
      onProgress(92, 'กำลังถอดรหัส GZIP ข้อมูลแผนที่บนเบราว์เซอร์...');
      await yieldIfVisible();
    }

    const [lutJsonStr, initialCsvText] = await Promise.all([
      lutB64 ? decompressGzip(lutB64).catch(() => null) : Promise.resolve(null),
      decompressGzip(csvB64)
    ]);

    // Release raw base64 payload (~60MB) for immediate GC
    if (rawPayload) {
      rawPayload.lut = '';
      rawPayload.csv = '';
    }
    if (global.__NOVA_RAW_MAP_PAYLOAD__ === rawPayload) {
      global.__NOVA_RAW_MAP_PAYLOAD__ = null;
    }

    let _lut = { co: [], ty: [], pv: [], st: [], rg: [], dt: [], subdt: [], prj: [], plaintiff: [], co_rgb: [] };
    if (lutJsonStr) {
      try {
        _lut = JSON.parse(lutJsonStr);
      } catch (e) {
        console.warn('Lookup JSON parse failed', e);
      }
    }

    if (typeof onProgress === 'function') {
      onProgress(95, 'กำลังวิเคราะห์ตารางพิกัด (Parsing CSV)...');
      await yieldIfVisible();
    }

    let csvText = initialCsvText;
    if (!global.d3 || typeof global.d3.csvParse !== 'function') {
      throw new Error('d3.csvParse unavailable');
    }
    const data = global.d3.csvParse(csvText);
    csvText = null;

    hydrateMapRows(data, _lut);

    if (typeof onProgress === 'function') {
      onProgress(98, 'กำลังสร้างดัชนีพิกัดและโครงการ (' + data.length.toLocaleString() + ' จุด)...');
      await yieldIfVisible();
    }

    const spatialGrid = buildSpatialGrid(data);
    const projIndex = buildProjectIndex(data, _lut);
    const typeCounts = computeTypeCounts(data);

    const cacheObj = {
      mtime: mtimeStr || String((rawPayload && rawPayload.mtime) || ''),
      lut: _lut,
      data: data,
      spatialGrid: spatialGrid,
      projIndex: projIndex,
      typeCounts: typeCounts,
      builtAt: Date.now()
    };

    const host = getParentHost();
    if (host) {
      host.__NOVA_MAP_CACHE__ = cacheObj;
    }
    return cacheObj;
  }

  // Expose legacy global symbol names so map_template.html has zero duplicate definitions
  global.BRAND_TAG_RULES = BRAND_TAG_RULES;
  global.getBrandSearchTag = getBrandSearchTag;
  global.isInvalidProjectName = isInvalidProjectName;
  global.cleanDisplayProjectName = cleanDisplayProjectName;
  global.normalizeProjectKeyword = normalizeProjectKeyword;
  global.decompressGzip = decompressGzip;
  global.buildSpatialGrid = buildSpatialGrid;

  global.NovaMapCache = {
    GRID_CELL_SIZE: GRID_CELL_SIZE,
    DEFAULT_CO_RGB: DEFAULT_CO_RGB,
    decompressGzip: decompressGzip,
    formatThbPriceStr: formatThbPriceStr,
    hydrateMapRows: hydrateMapRows,
    buildSpatialGrid: buildSpatialGrid,
    buildProjectIndex: buildProjectIndex,
    computeTypeCounts: computeTypeCounts,
    getValidParentCache: getValidParentCache,
    buildAndStoreParentCache: buildAndStoreParentCache,
    getParentBoundaryCache: getParentBoundaryCache,
    storeParentBoundaryCache: storeParentBoundaryCache
  };
})(typeof window !== 'undefined' ? window : globalThis);
