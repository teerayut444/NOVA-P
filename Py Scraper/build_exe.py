import os
import sys
import subprocess

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

print("=" * 75)
print("[BUILD] เริ่มต้นกระบวนการ Compile Scraper_Monthly_Parallel.exe")
print("=" * 75)

# 1. Install PyInstaller if missing
try:
    import PyInstaller
except ImportError:
    print("\n[1/3] กำลังติดตั้ง PyInstaller...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller"])
    import PyInstaller

import PyInstaller.__main__

base_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(base_dir, ".."))
os.chdir(base_dir)

print("\n[2/3] กำลัง Build ไฟล์ .exe ด้วย PyInstaller (กรุณารอสักครู่)...")

args = [
    "run_parallel_monthly.py",
    "--noconfirm",
    "--onefile",
    "--console",
    "--name", "Scraper_Monthly_Parallel",
    f"--specpath={os.path.abspath(base_dir)}",
    "--hidden-import=numpy",
    "--hidden-import=urllib3",
    "--hidden-import=pandas",
    "--hidden-import=requests",
    "--hidden-import=curl_cffi",
    "--hidden-import=bs4",
    "--hidden-import=openpyxl",
    "--hidden-import=pyarrow",
    "--hidden-import=convert_csv_to_parquet",
    "--hidden-import=merge_led_legal_multi_months",
    "--hidden-import=modules",
    "--hidden-import=modules.config",
    "--hidden-import=modules.config.constants",
    "--hidden-import=modules.services",
    "--hidden-import=modules.services.data_cleaner",
    "--hidden-import=scrape_baania_monthly",
    "--hidden-import=scrape_bam_monthly",
    "--hidden-import=scrape_chayo555_monthly",
    "--hidden-import=scrape_ghb_monthly",
    "--hidden-import=scrape_gsb_monthly",
    "--hidden-import=scrape_kbank_monthly",
    "--hidden-import=scrape_ktb_monthly",
    "--hidden-import=scrape_nayoo_monthly",
    "--hidden-import=scrape_sam_monthly",
    "--hidden-import=scrape_scb_monthly",
    "--hidden-import=scrape_zmyhome_monthly",
    "--hidden-import=scrape_led_monthly",
    "--hidden-import=scrape_led_legal",
    "--hidden-import=scrape_ddproperty_monthly",
    "--hidden-import=scrape_livinginsider_monthly",
    "--hidden-import=merge_csv_monthly",
    "--hidden-import=preflight_check",
    "--hidden-import=logger_util",
    "--hidden-import=timeout_handler",
    "--hidden-import=time_window_util",
    "--hidden-import=clean_location_util",
    "--hidden-import=clean_project_util",
    "--hidden-import=shapely",
    "--hidden-import=shapely.geometry",
    "--hidden-import=shapely.strtree",
    "--collect-all=shapely",
    "--collect-all=curl_cffi",
    f"--add-data={os.path.join(base_dir, 'subdistricts.geojson')};.",
    f"--add-data={os.path.join(base_dir, 'districts.geojson')};.",
    f"--add-data={os.path.join(base_dir, 'project_canonical_mapping.json')};.",
    f"--paths={os.path.abspath(base_dir)}",
    f"--paths={root_dir}",
    "--hidden-import=enrich_led_landsmaps",
    "--hidden-import=enrich_led_merge_landsmaps",
    f"--add-data={os.path.abspath(os.path.join(root_dir, 'convert_csv_to_parquet.py'))};.",
    f"--add-data={os.path.abspath(os.path.join(base_dir, 'clean_project_util.py'))};.",
    f"--add-data={os.path.abspath(os.path.join(base_dir, 'clean_project_util.py'))};Py Scraper",
    f"--add-data={os.path.abspath(os.path.join(base_dir, 'enrich_led_landsmaps.py'))};.",
    f"--add-data={os.path.abspath(os.path.join(base_dir, 'enrich_led_landsmaps.py'))};Py Scraper",
    f"--add-data={os.path.abspath(os.path.join(base_dir, 'enrich_led_merge_landsmaps.py'))};.",
    f"--add-data={os.path.abspath(os.path.join(base_dir, 'enrich_led_merge_landsmaps.py'))};Py Scraper",
]

# Bundle public DOL province/amphoe code table (never bundle scratch/ or userinfo!)
_dol_local = os.path.abspath(os.path.join(base_dir, 'dol_master_codes.json'))
_dol_legacy = os.path.abspath(os.path.join(root_dir, 'offline_landsmaps', 'data', 'dol_master_codes.json'))
if os.path.exists(_dol_local):
    args.append(f"--add-data={_dol_local};.")
elif os.path.exists(_dol_legacy):
    args.append(f"--add-data={_dol_legacy};offline_landsmaps/data")

def check_scraper_running():
    try:
        res = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Scraper_Monthly_Parallel.exe'], capture_output=True, text=True)
        return 'Scraper_Monthly_Parallel.exe' in res.stdout
    except Exception:
        return False

is_running = check_scraper_running()
if is_running:
    print("\n[WARN] พบว่า 'Scraper_Monthly_Parallel.exe' กำลังรันค้างอยู่ใน Task Manager!")
    print("       (หากไม่ปิดโปรแกรมเดิม ไฟล์บิลด์ใหม่จะถูกเซฟเป็น Scraper_Monthly_Parallel_New.exe)")

try:
    PyInstaller.__main__.run(args)
    print("\n" + "=" * 75)
    
    dist_candidates = [
        os.path.join(base_dir, "dist", "Scraper_Monthly_Parallel.exe"),
        os.path.abspath(os.path.join(base_dir, "..", "dist", "Scraper_Monthly_Parallel.exe")),
    ]
    dist_exe = next((p for p in dist_candidates if os.path.exists(p)), None)
    
    if dist_exe:
        print("[SUCCESS] PyInstaller Compile สำเร็จเรียบร้อยแล้ว!")
        import shutil
        
        # 1. คัดลอกไปโฟลเดอร์ Py Scraper/
        local_exe = os.path.join(base_dir, "Scraper_Monthly_Parallel.exe")
        try:
            shutil.copy2(dist_exe, local_exe)
            print(f"[PATH 1] ในโฟลเดอร์ Py Scraper : {local_exe}")
        except Exception as e_local:
            print(f"[WARN] ไม่สามารถก็อปปี้ลง Py Scraper ได้: {e_local}")
            
        # 2. คัดลอกไปโฟลเดอร์หลัก (Root)
        target_exe = os.path.abspath(os.path.join(base_dir, "..", "Scraper_Monthly_Parallel.exe"))
        try:
            shutil.copy2(dist_exe, target_exe)
            print(f"[PATH 2] หน้ารูทของโปรเจกต์   : {target_exe}")
        except (PermissionError, OSError):
            new_target = os.path.abspath(os.path.join(base_dir, "..", "Scraper_Monthly_Parallel_New.exe"))
            shutil.copy2(dist_exe, new_target)
            print(f"[WARN] เนื่องจากมี Scraper_Monthly_Parallel.exe ตัวเดิมกำลังทำงานอยู่")
            print(f"       ระบบจึงบันทึกไฟล์ใหม่ไว้ที่:\n       -> {new_target}")
            print(f"       (ปิดโปรแกรมเดิมใน Task Manager แล้วเปลี่ยนชื่อแทนที่ได้เลยครับ)")

        # ซิงค์ Root .spec ให้ตรงกับ Py Scraper/Scraper_Monthly_Parallel.spec
        local_spec = os.path.join(base_dir, "Scraper_Monthly_Parallel.spec")
        root_spec = os.path.join(root_dir, "Scraper_Monthly_Parallel.spec")
        if os.path.exists(local_spec):
            try:
                with open(local_spec, "r", encoding="utf-8") as sf:
                    spec_txt = sf.read()
                spec_txt_root = spec_txt.replace("['run_parallel_monthly.py']", "['Py Scraper/run_parallel_monthly.py']")
                with open(root_spec, "w", encoding="utf-8") as rf:
                    rf.write(spec_txt_root)
                print(f"[SYNC] ซิงค์ Root spec เรียบร้อย: {root_spec}")
            except Exception as e_spec:
                print(f"[WARN] ไม่สามารถซิงค์ Root spec ได้: {e_spec}")

        # ทำความสะอาด build/dist
        shutil.rmtree(os.path.dirname(dist_exe), ignore_errors=True)
        shutil.rmtree(os.path.join(base_dir, "build"), ignore_errors=True)
        shutil.rmtree(os.path.abspath(os.path.join(base_dir, "..", "build")), ignore_errors=True)
    else:
        print("[ERROR] ไม่พบไฟล์ที่สร้างในโฟลเดอร์ dist กรุณาตรวจสอบ log ข้อผิดพลาดด้านบน")
    print("=" * 75)
except Exception as e:
    print(f"\n[ERROR] เกิดข้อผิดพลาดในการสร้าง EXE: {e}")
    sys.exit(1)

try:
    if "--no-pause" not in sys.argv and sys.stdin and sys.stdin.isatty():
        input("\nกด Enter เพื่อปิดหน้าต่างนี้...")
except (EOFError, KeyboardInterrupt):
    pass
