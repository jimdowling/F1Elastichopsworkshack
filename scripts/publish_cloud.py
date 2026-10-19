"""Optional explicit Hopsworks publish of the original lab features. Without --write, this is a network-free plan."""
from pathlib import Path
import argparse, sys, json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.engine import LabEngine
from src.cloud import GROUPS, validate_prefix, HopsworksPublisher

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prefix',default='pitlane_yourteam',help='Unique destination prefix, e.g. pitlane_alexdemo')
    p.add_argument('--write',action='store_true',help='Actually publish to the configured Hopsworks project. May incur provider charges.')
    args=p.parse_args();validate_prefix(args.prefix)
    lab=LabEngine();frames={g:lab.store.read(g) for g in GROUPS}
    plan=[{'destination':args.prefix+'_'+g,'rows':len(f)} for g,f in frames.items()]
    print(json.dumps({'mode':'WRITE' if args.write else 'DRY RUN — no external calls','target':'hopsworks','plan':plan},indent=2))
    if not args.write:return
    from src.settings import Settings
    report=HopsworksPublisher(Settings.load()).publish(args.prefix,frames)
    target=ROOT/'data'/'hopsworks-publish-report.json';target.write_text(json.dumps(report,indent=2))
    print('Published and verified:',target)
    print('The running web app still uses its local lab backends. This bridge does not switch the app to cloud inference.')
if __name__=='__main__':main()
