# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('C:/Users/Teerayut.N/.vscode/extensions/NOVA/Py Scraper/subdistricts.geojson', '.'), ('C:/Users/Teerayut.N/.vscode/extensions/NOVA/Py Scraper/districts.geojson', '.'), ('C:/Users/Teerayut.N/.vscode/extensions/NOVA/Py Scraper/project_canonical_mapping.json', '.'), ('C:/Users/Teerayut.N/.vscode/extensions/NOVA/convert_csv_to_parquet.py', '.'), ('C:/Users/Teerayut.N/.vscode/extensions/NOVA/Py Scraper/clean_project_util.py', '.'), ('C:/Users/Teerayut.N/.vscode/extensions/NOVA/Py Scraper/clean_project_util.py', 'Py Scraper'), ('C:/Users/Teerayut.N/.vscode/extensions/NOVA/Py Scraper/enrich_led_landsmaps.py', '.'), ('C:/Users/Teerayut.N/.vscode/extensions/NOVA/Py Scraper/enrich_led_landsmaps.py', 'Py Scraper'), ('C:/Users/Teerayut.N/.vscode/extensions/NOVA/Py Scraper/enrich_led_merge_landsmaps.py', '.'), ('C:/Users/Teerayut.N/.vscode/extensions/NOVA/Py Scraper/enrich_led_merge_landsmaps.py', 'Py Scraper'), ('C:/Users/Teerayut.N/.vscode/extensions/NOVA/Py Scraper/dol_master_codes.json', '.')]
binaries = []
hiddenimports = ['numpy', 'urllib3', 'pandas', 'requests', 'curl_cffi', 'bs4', 'openpyxl', 'pyarrow', 'convert_csv_to_parquet', 'merge_led_legal_multi_months', 'modules', 'modules.config', 'modules.config.constants', 'modules.services', 'modules.services.data_cleaner', 'scrape_baania_monthly', 'scrape_bam_monthly', 'scrape_chayo555_monthly', 'scrape_ghb_monthly', 'scrape_gsb_monthly', 'scrape_kbank_monthly', 'scrape_ktb_monthly', 'scrape_nayoo_monthly', 'scrape_sam_monthly', 'scrape_scb_monthly', 'scrape_zmyhome_monthly', 'scrape_led_monthly', 'scrape_led_legal', 'scrape_ddproperty_monthly', 'scrape_livinginsider_monthly', 'merge_csv_monthly', 'preflight_check', 'logger_util', 'timeout_handler', 'time_window_util', 'clean_location_util', 'clean_project_util', 'shapely', 'shapely.geometry', 'shapely.strtree', 'enrich_led_landsmaps', 'enrich_led_merge_landsmaps']
tmp_ret = collect_all('shapely')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('curl_cffi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['run_parallel_monthly.py'],
    pathex=['C:/Users/Teerayut.N/.vscode/extensions/NOVA/Py Scraper', 'C:/Users/Teerayut.N/.vscode/extensions/NOVA'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Scraper_Monthly_Parallel',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
