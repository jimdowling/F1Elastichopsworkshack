"""App-owned tables in the project's RonDB database (the online feature store), replacing SQLite.

Hopsworks injects MYSQL_HOST/PORT/DB/USER and MYSQL_PASSWORD_SECRET_NAME into the app pod
(db_access, the default). The password is read from the Hopsworks secrets store. The app connects
as its own database user, which cannot create or alter tables, so each table is created with
app.create_table(): Hopsworks runs the CREATE TABLE on disk in RonDB, grants the app the table,
prefixes it with app.table_prefix (app_<app name>__) and drops it when the app is deleted. Apps
created before table registration (managed_db False) keep the unprefixed app_pitlane_* names,
create them themselves and need a Data Owner start.

Outside a Hopsworks pod (no MYSQL_HOST) the same interface is kept in process memory. Inside one, a
failure to reach RonDB fails the start instead: state silently kept in memory is lost on restart.

Tables (logical name -> <prefix><name>)
  race_pace     per-driver race-pace features computed by the dashboard
  lab_features  the experiment feature tables (pace/dna/strategy/ghost/...) per race
  cache         compressed derived payloads (lab telemetry inputs, replay series)
"""
from threading import RLock
import io, json, logging, os, zlib

import pandas as pd

log = logging.getLogger('pitlane.appdb')
TABLES = ('race_pace', 'lab_features', 'cache')
# Columns and indexes of each table, what goes inside CREATE TABLE's parentheses.
DEFINITIONS = {
    'race_pace': """id VARCHAR(160) NOT NULL, season INT NOT NULL, round_number INT NOT NULL, payload TEXT NOT NULL,
         updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
         PRIMARY KEY (id), KEY idx_race (season, round_number)""",
    'lab_features': """race_key VARCHAR(16) NOT NULL, name VARCHAR(64) NOT NULL, row_count INT NOT NULL, payload LONGBLOB NOT NULL,
         updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
         PRIMARY KEY (race_key, name)""",
    'cache': """cache_key VARCHAR(190) NOT NULL, payload LONGBLOB NOT NULL,
         updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
         PRIMARY KEY (cache_key)""",
}


def table_names():
    """Create the app's tables and return ({logical name: SQL name}, whether Hopsworks created them).

    The app is looked up by its job name (HOPSWORKS_JOB_NAME, set in the app pod; PITLANE_APP_NAME overrides).
    create_table is idempotent, so this runs on every start.
    """
    import hopsworks
    project = hopsworks.login(engine='python')
    app_name = os.environ.get('PITLANE_APP_NAME') or os.environ['HOPSWORKS_JOB_NAME']
    app = project.get_app_api().get_app(app_name)
    if not app.managed_db:
        log.warning('App %s predates table registration; using unprefixed app_pitlane_* tables (needs a Data Owner start)', app_name)
        return {t: f'app_pitlane_{t}' for t in TABLES}, False
    if not hasattr(app, 'create_table'):
        raise RuntimeError('The hopsworks client in this environment predates App.create_table; '
                           'install a client where Hopsworks creates app tables in the app environment')
    return {t: app.create_table(t, DEFINITIONS[t]) for t in TABLES}, True


def pack(value): return zlib.compress(json.dumps(value, separators=(',', ':'), allow_nan=False).encode(), 6)
def unpack(blob): return json.loads(zlib.decompress(blob))


class MemoryBackend:
    name = 'process memory (no MYSQL_HOST; local development)'

    def __init__(self): self.tables = {'app_pitlane_race_pace': {}, 'app_pitlane_lab_features': {}, 'app_pitlane_cache': {}}
    def put_pace(self, season, round_number, rows):
        for r in rows: self.tables['app_pitlane_race_pace'][r['id']] = (season, round_number, json.dumps(r, separators=(',', ':')))
    def get_pace(self, season, round_number):
        return [json.loads(p) for s, r, p in self.tables['app_pitlane_race_pace'].values() if s == season and r == round_number]
    def count_pace(self): return len(self.tables['app_pitlane_race_pace'])
    def put_frame(self, race_key, name, blob, rows): self.tables['app_pitlane_lab_features'][(race_key, name)] = (rows, blob)
    def get_frame(self, race_key, name):
        v = self.tables['app_pitlane_lab_features'].get((race_key, name)); return None if v is None else v[1]
    def frame_counts(self, race_key): return {n: rows for (k, n), (rows, _) in self.tables['app_pitlane_lab_features'].items() if k == race_key}
    def get_cache(self, key): return self.tables['app_pitlane_cache'].get(key)
    def put_cache(self, key, blob): self.tables['app_pitlane_cache'][key] = blob


class RonDBBackend:
    def __init__(self):
        import pymysql, hopsworks
        password = os.environ.get('MYSQL_PASSWORD')
        if password is None:
            hopsworks.login(engine='python')
            password = hopsworks.get_secrets_api().get(os.environ['MYSQL_PASSWORD_SECRET_NAME'])
        self.settings = dict(host=os.environ['MYSQL_HOST'], port=int(os.environ.get('MYSQL_PORT', '3306')), user=os.environ['MYSQL_USER'],
                             password=password, database=os.environ['MYSQL_DB'], autocommit=True, charset='utf8mb4')
        self.pymysql = pymysql; self.conn = None; self.lock = RLock()
        self.t, created = table_names()
        self.name = f"RonDB {os.environ['MYSQL_DB']} ({', '.join(self.t.values())})"
        if not created:
            with self.cursor() as cur:
                for name, definition in DEFINITIONS.items():
                    cur.execute(f"CREATE TABLE IF NOT EXISTS {self.t[name]} ({definition}) "
                                "ENGINE=NDBCLUSTER DEFAULT CHARSET=utf8mb4")

    def cursor(self):
        with self.lock:
            if self.conn is None: self.conn = self.pymysql.connect(**self.settings)
            else: self.conn.ping(reconnect=True)
            return self.conn.cursor()

    def run(self, sql, args=None, fetch=False, many=False):
        with self.lock, self.cursor() as cur:
            (cur.executemany if many else cur.execute)(sql, args)
            return cur.fetchall() if fetch else None

    def put_pace(self, season, round_number, rows):
        if rows: self.run(f'INSERT INTO {self.t["race_pace"]} (id, season, round_number, payload) VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE payload=VALUES(payload)',
                          [(r['id'], season, round_number, json.dumps(r, separators=(',', ':'))) for r in rows], many=True)
    def get_pace(self, season, round_number):
        return [json.loads(p) for (p,) in self.run(f'SELECT payload FROM {self.t["race_pace"]} WHERE season=%s AND round_number=%s', (season, round_number), fetch=True)]
    def count_pace(self): return self.run(f'SELECT COUNT(*) FROM {self.t["race_pace"]}', fetch=True)[0][0]
    def put_frame(self, race_key, name, blob, rows):
        self.run(f'INSERT INTO {self.t["lab_features"]} (race_key, name, row_count, payload) VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE row_count=VALUES(row_count), payload=VALUES(payload)',
                 (race_key, name, rows, blob))
    def get_frame(self, race_key, name):
        r = self.run(f'SELECT payload FROM {self.t["lab_features"]} WHERE race_key=%s AND name=%s', (race_key, name), fetch=True); return r[0][0] if r else None
    def frame_counts(self, race_key):
        return dict(self.run(f'SELECT name, row_count FROM {self.t["lab_features"]} WHERE race_key=%s', (race_key,), fetch=True))
    def get_cache(self, key):
        r = self.run(f'SELECT payload FROM {self.t["cache"]} WHERE cache_key=%s', (key,), fetch=True); return r[0][0] if r else None
    def put_cache(self, key, blob):
        self.run(f'INSERT INTO {self.t["cache"]} (cache_key, payload) VALUES (%s,%s) ON DUPLICATE KEY UPDATE payload=VALUES(payload)', (key, blob))


class AppStore:
    """Pace features, per-race lab feature tables, and a derived-payload cache."""
    CACHE_VERSION = 'v2'

    def __init__(self, backend=None):
        if backend is None:
            backend = RonDBBackend() if 'MYSQL_HOST' in os.environ else MemoryBackend()
        self.backend = backend; self.lock = RLock()

    @property
    def name(self): return self.backend.name

    def put_pace(self, season, round_number, rows):
        with self.lock: self.backend.put_pace(season, round_number, rows); return self.backend.get_pace(season, round_number)
    def pace_count(self):
        with self.lock: return self.backend.count_pace()

    def put_read(self, race_key, name, frame):
        """Persist a feature table and read it back (the round trip the experiments consume)."""
        if not name.replace('_', '').isalnum(): raise ValueError('Invalid table name')
        if 'id' in frame and not frame.id.is_unique: raise ValueError('Feature primary keys must be unique')
        buf = io.BytesIO(); frame.to_parquet(buf, index=False)
        with self.lock:
            self.backend.put_frame(race_key, name, buf.getvalue(), len(frame))
            blob = self.backend.get_frame(race_key, name)
        read = pd.read_parquet(io.BytesIO(blob))
        if 'id' in read: read = read.sort_values('id').reset_index(drop=True)
        if len(read) != len(frame): raise RuntimeError('Feature-table round-trip row count mismatch')
        if 'id' in frame: read = read.set_index('id').loc[frame['id']].reset_index()
        return read

    def read(self, race_key, name):
        with self.lock: blob = self.backend.get_frame(race_key, name)
        if blob is None: raise ValueError('Unknown table')
        return pd.read_parquet(io.BytesIO(blob))

    def counts(self, race_key):
        with self.lock: return self.backend.frame_counts(race_key)

    def cached(self, key, build):
        """JSON payload from app_pitlane_cache, computing and storing it on a miss."""
        key = f'{self.CACHE_VERSION}:{key}'
        with self.lock: blob = self.backend.get_cache(key)
        if blob is not None:
            try: return unpack(blob)
            except Exception: log.warning('Discarding unreadable cache entry %s', key)
        value = build()
        try:
            with self.lock: self.backend.put_cache(key, pack(value))
        except Exception as e: log.warning('Could not cache %s: %s', key, e)
        return value


STORE = None; LOCK = RLock()


def store():
    global STORE
    with LOCK:
        if STORE is None: STORE = AppStore()
        return STORE
