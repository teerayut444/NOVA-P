import sys
from pathlib import Path
import traceback

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

def test():
    try:
        from modules.services.data_loader import load_properties_data, get_data_mtime
        df = load_properties_data(get_data_mtime())
        print("Loaded data shape:", df.shape if df is not None else None)
        print("Columns in loaded data:", list(df.columns) if df is not None else None)
        assert df is not None and not df.empty, "Expected non-empty dataset"
    except Exception:
        print("ERROR during data loading:")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    test()
