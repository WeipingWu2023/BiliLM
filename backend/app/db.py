import json
import os
import sqlite3
import time
from contextlib import contextmanager, closing
from pathlib import Path
from uuid import uuid4

DATA = Path(os.getenv('BILILM_DATA', Path(__file__).resolve().parents[2] / 'data')).resolve()


@contextmanager
def connection():
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA / 'bililm.sqlite3', timeout=30)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init():
    with connection() as con:
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='videos'").fetchone() and not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone():
            backup_dir = DATA/'backups'; backup_dir.mkdir(exist_ok=True)
            with closing(sqlite3.connect(backup_dir/('pre-accuracy-'+uuid4().hex+'.sqlite3'))) as backup:
                con.backup(backup)
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript('''
        CREATE TABLE IF NOT EXISTS videos (
          id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
          creator TEXT DEFAULT '', thumbnail TEXT DEFAULT '', duration REAL DEFAULT 0,
          segments TEXT, readable TEXT DEFAULT '', provenance TEXT DEFAULT '',
          revision INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(id),
          status TEXT NOT NULL, progress INTEGER DEFAULT 0, stage TEXT DEFAULT '等待处理',
          error TEXT, payload TEXT NOT NULL, attempts INTEGER DEFAULT 0,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE UNIQUE INDEX IF NOT EXISTS active_job ON jobs(video_id)
          WHERE status IN ('queued','running');
        CREATE TRIGGER IF NOT EXISTS preserve_original BEFORE UPDATE OF segments ON videos
          WHEN OLD.segments IS NOT NULL BEGIN SELECT RAISE(ABORT, 'original transcript is immutable'); END;
        ''')
        if 'deleted_at' not in {r[1] for r in con.execute('PRAGMA table_info(videos)')}:
            con.execute('ALTER TABLE videos ADD COLUMN deleted_at TEXT')
        columns = {r[1] for r in con.execute('PRAGMA table_info(jobs)')}
        for name,kind in (('worker_id','TEXT'),('lease_token','TEXT'),('lease_until','REAL')):
            if name not in columns:
                con.execute(f'ALTER TABLE jobs ADD COLUMN {name} {kind}')
        from .versions import init as init_versions
        init_versions(con)
        from .ground_truth import init as init_ground_truth
        init_ground_truth(con)
        from .learning import init as init_learning
        init_learning(con)
        from .model_manager import init as init_models
        init_models(con)


def enqueue(key, url, title, payload):
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        video = con.execute('SELECT * FROM videos WHERE id=?', (key,)).fetchone()
        if video and video['deleted_at']:
            con.execute('UPDATE videos SET deleted_at=NULL WHERE id=?',(key,))
        if video and video['segments'] and not payload.get('retranscribe'):
            return {'video_id': key, 'cached': True, 'job_id': None}
        active = con.execute("SELECT id FROM jobs WHERE video_id=? AND status IN ('queued','running')", (key,)).fetchone()
        if active:
            if payload.get('retranscribe'):
                existing = json.loads(con.execute('SELECT payload FROM jobs WHERE id=?',(active['id'],)).fetchone()['payload'])
                if existing.get('config')!=payload.get('config'):
                    raise ValueError('该视频已有其他配置的活动任务；请等待完成后再重新转录')
            return {'video_id': key, 'cached': False, 'job_id': active['id']}
        con.execute('INSERT OR IGNORE INTO videos(id,url,title) VALUES(?,?,?)', (key, url, title))
        jid = uuid4().hex
        con.execute('INSERT INTO jobs(id,video_id,status,payload) VALUES(?,?,?,?)', (jid, key, 'queued', json.dumps(payload)))
        return {'video_id': key, 'cached': False, 'job_id': jid}


def get_video(key):
    with connection() as con:
        row = con.execute('SELECT * FROM videos WHERE id=? AND deleted_at IS NULL', (key,)).fetchone()
    if row is None:
        return None
    video = dict(row)
    video['segments'] = json.loads(video['segments']) if video['segments'] else []
    return video


class LeaseLost(RuntimeError):
    pass


def trash_video(key,restore=False):
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        if not con.execute('SELECT 1 FROM videos WHERE id=?',(key,)).fetchone():
            raise ValueError('未找到笔记')
        if restore:
            con.execute('UPDATE videos SET deleted_at=NULL WHERE id=?',(key,))
            if con.execute('SELECT 1 FROM videos WHERE id=? AND segments IS NULL',(key,)).fetchone():
                last=con.execute('SELECT id,status FROM jobs WHERE video_id=? ORDER BY rowid DESC LIMIT 1',(key,)).fetchone()
                if last and last['status']=='cancelled':
                    con.execute("UPDATE jobs SET status='queued',progress=0,stage='笔记已恢复，等待处理' WHERE id=?",(last['id'],))
        else:
            con.execute('UPDATE videos SET deleted_at=COALESCE(deleted_at,CURRENT_TIMESTAMP) WHERE id=?',(key,))
            con.execute("UPDATE jobs SET status='cancelled',stage='笔记已移入回收站',error=NULL,lease_token=NULL,lease_until=NULL WHERE video_id=? AND status IN ('queued','running')",(key,))


def fence(con,jid,token):
    if con.execute('SELECT 1 FROM jobs JOIN videos ON videos.id=jobs.video_id WHERE jobs.id=? AND videos.deleted_at IS NOT NULL',(jid,)).fetchone():
        raise LeaseLost('笔记已删除，任务不再写入结果')
    if token and not con.execute("SELECT 1 FROM jobs WHERE id=? AND status='running' AND lease_token=? AND lease_until>?",(jid,token,time.time())).fetchone():
        raise LeaseLost('任务租约已失效，此 worker 不再提交结果')


def update_job(jid, _lease_token=None, **values):
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        fence(con,jid,_lease_token)
        con.execute('UPDATE jobs SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?', (*values.values(), jid))


def claim(worker_id='legacy', capabilities=None, lease_seconds=120):
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute("UPDATE jobs SET status='queued',worker_id=NULL,lease_token=NULL,lease_until=NULL,stage='租约到期，等待恢复' WHERE status='running' AND (lease_until IS NULL OR lease_until<?)",(time.time(),))
        rows = con.execute("SELECT jobs.* FROM jobs JOIN videos ON videos.id=jobs.video_id WHERE jobs.status='queued' AND videos.deleted_at IS NULL ORDER BY jobs.created_at,jobs.rowid").fetchall()
        row = next((r for r in rows if capabilities is None or json.loads(r['payload']).get('config',{}).get('device','auto') in ('auto',*capabilities)),None)
        if not row:
            return None
        token=uuid4().hex
        con.execute("UPDATE jobs SET status='running',attempts=attempts+1,error=NULL,worker_id=?,lease_token=?,lease_until=? WHERE id=?", (worker_id,token,time.time()+lease_seconds,row['id']))
        return dict(con.execute('SELECT * FROM jobs WHERE id=?',(row['id'],)).fetchone())


def recover():
    with connection() as con:
        con.execute("UPDATE jobs SET status='queued',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=0,stage='租约到期，重新排队' WHERE status='running' AND (lease_until IS NULL OR lease_until<?)",(time.time(),))


def heartbeat(jid,token):
    with connection() as con:
        con.execute('BEGIN IMMEDIATE'); fence(con,jid,token)
        con.execute('UPDATE jobs SET lease_until=? WHERE id=?',(time.time()+120,jid))


def save(key, metadata, segments, readable, provenance, jid=None, token=None):
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        if jid:
            fence(con,jid,token)
        con.execute('UPDATE videos SET title=?,creator=?,thumbnail=?,duration=? WHERE id=?',
                    (metadata['title'], metadata.get('creator',''), metadata.get('thumbnail',''), metadata.get('duration',0), key))
        con.execute('UPDATE videos SET segments=?,readable=?,provenance=? WHERE id=? AND segments IS NULL',
                    (json.dumps(segments, ensure_ascii=False), readable, provenance, key))


def save_metadata(key, metadata, jid=None, token=None):
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        if jid:
            fence(con,jid,token)
        con.execute('UPDATE videos SET title=?,creator=?,thumbnail=?,duration=? WHERE id=?',
                    (metadata['title'], metadata.get('creator',''), metadata.get('thumbnail',''), metadata.get('duration',0), key))
