"""Experiment models in the Hopsworks Model Registry: download if present, else train and register.

One model name per experiment and race (pitlane_<kind>_<season>_<round>). A saved model is reused
only when its training-data digest and the xgboost/scikit-learn versions match this runtime;
otherwise the caller retrains and a new version is registered.
"""
import json, logging, os, tempfile, threading
import joblib, sklearn, xgboost

log = logging.getLogger('pitlane.registry')
RUNTIME = {'xgboost': xgboost.__version__, 'scikit-learn': sklearn.__version__}


def minor(v): return '.'.join(v.split('.')[:2])


class ModelStore:
    def __init__(self):
        self.lock = threading.RLock(); self.mr = None

    def registry(self):
        with self.lock:
            if self.mr is None:
                from .hopsdata import hops
                self.mr = hops().project().get_model_registry()
            return self.mr

    def load(self, name, digest):
        """(model object, version) for the newest compatible version, or None."""
        try:
            models = self.registry().get_models(name) or []
        except Exception as e:
            log.warning('Model Registry lookup for %s failed: %s', name, e); return None
        for m in sorted(models, key=lambda m: m.version, reverse=True):
            try:
                path = m.download()
                meta = json.load(open(os.path.join(path, 'pitlane.json')))
                if meta.get('training_digest') != digest:
                    log.info('%s v%s was trained on different data; skipping', name, m.version); continue
                if any(minor(meta.get('runtime', {}).get(k, '')) != minor(v) for k, v in RUNTIME.items()):
                    log.info('%s v%s was built with %s, runtime has %s; skipping', name, m.version, meta.get('runtime'), RUNTIME); continue
                return joblib.load(os.path.join(path, 'model.joblib')), m.version
            except Exception as e:
                log.warning('Could not load %s v%s: %s', name, m.version, e)
        return None

    def save(self, name, obj, digest, metrics, description):
        """Register a new version; returns the version number."""
        with tempfile.TemporaryDirectory() as d:
            joblib.dump(obj, os.path.join(d, 'model.joblib'))
            json.dump({'training_digest': digest, 'runtime': RUNTIME, 'metrics': metrics}, open(os.path.join(d, 'pitlane.json'), 'w'))
            model = self.registry().python.create_model(name=name, metrics={k: float(v) for k, v in metrics.items()}, description=description[:900])
            # In an app pod HOPSWORKS_JOB_NAME names the app's PythonApp job; the SDK then asks the backend to
            # version that program, which it refuses ("cannot version program for job type:PythonApp").
            # Hide it for the save only, so the model registers without the job provenance link.
            with self.lock:
                job = os.environ.pop('HOPSWORKS_JOB_NAME', None)
                try: model.save(d)
                finally:
                    if job is not None: os.environ['HOPSWORKS_JOB_NAME'] = job
            return model.version


STORE = None; LOCK = threading.RLock()


def models():
    global STORE
    with LOCK:
        if STORE is None: STORE = ModelStore()
        return STORE
