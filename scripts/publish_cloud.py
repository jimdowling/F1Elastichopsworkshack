"""Optional explicit cloud publish. Without --write, this is a network-free plan."""
from pathlib import Path
import argparse, os, sys, json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.engine import LabEngine
from src.cloud import GROUPS, validate_prefix, elastic_name, ElasticPublisher, HopsworksPublisher

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--target',choices=['elastic','hopsworks'],required=True)
    p.add_argument('--prefix',default='pitlane_yourteam',help='Unique destination prefix, e.g. pitlane_alexdemo')
    p.add_argument('--write',action='store_true',help='Actually publish to the configured destination. May incur provider charges.')
    args=p.parse_args();validate_prefix(args.prefix)
    lab=LabEngine();frames={g:lab.store.read(g) for g in GROUPS}
    if args.target=='elastic':frames={'race_laps':lab.laps,'pace_results':lab.pace,**frames}
    plan=[{'destination':elastic_name(args.prefix,g) if args.target=='elastic' else args.prefix+'_'+g,'rows':len(f)} for g,f in frames.items()]
    print(json.dumps({'mode':'WRITE' if args.write else 'DRY RUN — no external calls','target':args.target,'plan':plan},indent=2))
    if not args.write:return
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT/'.env')
    except ImportError:pass
    if args.target=='elastic':
        publisher=ElasticPublisher(os.environ.get('ELASTICSEARCH_URL',''),os.environ.get('ELASTICSEARCH_API_KEY',''))
    else:
        publisher=HopsworksPublisher(os.environ.get('HOPSWORKS_HOST',''),os.environ.get('HOPSWORKS_PROJECT',''),os.environ.get('HOPSWORKS_API_KEY',''))
    report=publisher.publish(args.prefix,frames)
    target=ROOT/'data'/f'{args.target}-publish-report.json';target.write_text(json.dumps(report,indent=2))
    print('Published and verified:',target)
    print('The running web app still uses its local backends. This bridge does not switch the app to cloud inference/search.')
if __name__=='__main__':main()
