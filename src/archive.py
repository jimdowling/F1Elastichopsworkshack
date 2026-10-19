"""Package source, compiled UI, curated observations, and test evidence; omit secrets/dependencies."""
from pathlib import Path
import os,zipfile
EXCLUDE_DIRS={'.git','.cache','.venv','node_modules','__pycache__','.pytest_cache','.ruff_cache','.mypy_cache','.hopsworks','.hsfs','connection_state','certificates','.secrets'}
def create_archive(root,destination):
    root=Path(root).resolve();destination=Path(destination).resolve()
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for folder,dirs,files in os.walk(root):
            dirs[:]=sorted(d for d in dirs if d not in EXCLUDE_DIRS)
            for name in sorted(files):
                p=Path(folder)/name
                if p.resolve()==destination:continue
                if (name.startswith('.env') and name!='.env.example') or name.endswith(('.log','.key','.pem','.jks','.p12','.pfx','.crt','.cer','-journal','-wal','-shm','-publish-report.json')):continue
                if p.is_symlink():continue
                z.write(p,Path('pitlane-lab')/p.relative_to(root))
    return destination
