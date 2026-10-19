from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.archive import create_archive
p=create_archive(ROOT,ROOT.parent/'pitlane-lab.zip')
print(f'{p} ({p.stat().st_size/1_000_000:.2f} MB)')
