import hashlib
import json
from uuid import uuid4
from . import db
from .transcript import clean


def init(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS runs (
      id TEXT PRIMARY KEY, video_id TEXT NOT NULL, raw TEXT NOT NULL,
      proofread TEXT NOT NULL, readable_segments TEXT NOT NULL, readable TEXT NOT NULL,
      proof_revision INTEGER DEFAULT 0, readable_revision INTEGER DEFAULT 0,
      mapped INTEGER DEFAULT 1, provenance TEXT NOT NULL, config TEXT NOT NULL,
      metrics TEXT NOT NULL, audio TEXT, playback TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS corrections (
      id TEXT PRIMARY KEY, run_id TEXT NOT NULL, segment_index INTEGER NOT NULL,
      before_text TEXT NOT NULL, after_text TEXT NOT NULL, reason TEXT NOT NULL,
      uncertain INTEGER NOT NULL, state TEXT NOT NULL, source TEXT NOT NULL,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS change_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, version TEXT NOT NULL,
      event TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TRIGGER IF NOT EXISTS immutable_run BEFORE UPDATE OF raw ON runs
      BEGIN SELECT RAISE(ABORT,'raw run transcript is immutable'); END;
    CREATE TRIGGER IF NOT EXISTS immutable_run_delete BEFORE DELETE ON runs
      BEGIN SELECT RAISE(ABORT,'run deletion is disabled'); END;
    CREATE TRIGGER IF NOT EXISTS immutable_execution BEFORE UPDATE OF config,metrics,audio,playback,provenance,video_id,id ON runs
      BEGIN SELECT RAISE(ABORT,'run provenance and execution metadata are immutable'); END;
    CREATE TRIGGER IF NOT EXISTS immutable_log_update BEFORE UPDATE ON change_log
      BEGIN SELECT RAISE(ABORT,'change log is append-only'); END;
    CREATE TRIGGER IF NOT EXISTS immutable_log_delete BEFORE DELETE ON change_log
      BEGIN SELECT RAISE(ABORT,'change log is append-only'); END;
    ''')
    for video in con.execute('SELECT * FROM videos WHERE segments IS NOT NULL').fetchall():
        if con.execute('SELECT 1 FROM runs WHERE video_id=?',(video['id'],)).fetchone():
            continue
        rows = json.loads(video['segments'])
        readable_rows = [{**r,'text':clean([r])} for r in rows]
        rid = 'legacy-' + hashlib.sha256(video['id'].encode()).hexdigest()[:24]
        con.execute('INSERT INTO runs(id,video_id,raw,proofread,readable_segments,readable,mapped,provenance,config,metrics) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (rid,video['id'],video['segments'],video['segments'],json.dumps(readable_rows,ensure_ascii=False),video['readable'],int(video['readable']==clean(rows)),video['provenance'],json.dumps({'legacy':True}),'{}'))


def _insert(con,rid,key,rows,provenance,config,metrics,audio,playback):
    original = json.dumps(rows,ensure_ascii=False)
    con.execute('INSERT OR IGNORE INTO runs(id,video_id,raw,proofread,readable_segments,readable,provenance,config,metrics,audio,playback) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (rid,key,original,original,json.dumps([{**r,'text':clean([r])} for r in rows],ensure_ascii=False),clean(rows),provenance,json.dumps(config,ensure_ascii=False),json.dumps(metrics),audio,playback))


def create(rid, key, rows, provenance, config, metrics, audio=None, playback=None, token=None):
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE'); db.fence(con,rid,token)
        _insert(con,rid,key,rows,provenance,config,metrics,audio,playback)


def commit_job(job,metadata,rows,provenance,config,metrics,audio=None,playback=None):
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE'); db.fence(con,job['id'],job.get('lease_token'))
        _insert(con,job['id'],job['video_id'],rows,provenance,config,metrics,audio,playback)
        con.execute('UPDATE videos SET title=?,creator=?,thumbnail=?,duration=? WHERE id=?',
                    (metadata['title'],metadata.get('creator',''),metadata.get('thumbnail',''),metadata.get('duration',0),job['video_id']))
        con.execute('UPDATE videos SET segments=?,readable=?,provenance=? WHERE id=? AND segments IS NULL',
                    (json.dumps(rows,ensure_ascii=False),clean(rows),provenance,job['video_id']))
        con.execute("UPDATE jobs SET status='completed',progress=100,stage='转录完成' WHERE id=?",(job['id'],))


def get(rid):
    with db.connection() as con:
        row = con.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
        if not row:
            return None
        result = dict(row)
        for field in ('audio','playback'):
            if result[field]:
                result[field]=result[field].replace('\\','/')
        for field in ('raw','proofread','readable_segments','config','metrics'):
            result[field] = json.loads(result[field])
        result['corrections'] = [dict(r) for r in con.execute('SELECT * FROM corrections WHERE run_id=? ORDER BY created_at,rowid',(rid,))]
        result['change_log'] = [dict(r) for r in con.execute('SELECT * FROM change_log WHERE run_id=? ORDER BY id',(rid,))]
    return result


def list_runs(key):
    with db.connection() as con:
        rows = [dict(r) for r in con.execute('SELECT id,provenance,created_at,config,metrics FROM runs WHERE video_id=? ORDER BY created_at DESC,rowid DESC',(key,))]
    for row in rows:
        row['config']=json.loads(row['config']); row['metrics']=json.loads(row['metrics'])
    return rows


def log(con,rid,version,event,details):
    con.execute('INSERT INTO change_log(run_id,version,event,details) VALUES(?,?,?,?)',(rid,version,event,json.dumps(details,ensure_ascii=False)))


def edit(rid, version, texts, revision, source='human', reason='人工逐段修改'):
    if version not in ('proofread','readable'):
        raise ValueError('原始稿不能编辑')
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
        if not row:
            raise ValueError('未找到转录版本')
        column = 'proofread' if version == 'proofread' else 'readable_segments'
        rev = 'proof_revision' if version == 'proofread' else 'readable_revision'
        if row[rev] != revision:
            raise ValueError('版本已变化，请重新加载后保存')
        segments = json.loads(row[column])
        if len(texts) != len(segments) or any(not isinstance(t,str) or len(t)>10000 for t in texts):
            raise ValueError('必须保留全部片段的时间戳映射')
        changes = []
        for i,(segment,text) in enumerate(zip(segments,texts)):
            if text != segment['text']:
                changes.append({'index':i,'start':segment['start'],'end':segment['end'],'before':segment['text'],'after':text,'reason':reason,'source':source})
                segment['text'] = text
        con.execute(f'UPDATE runs SET {column}=?,{rev}={rev}+1 WHERE id=?',(json.dumps(segments,ensure_ascii=False),rid))
        if version == 'readable':
            con.execute('UPDATE runs SET readable=?,mapped=1 WHERE id=?',(clean(segments),rid))
        log(con,rid,version,'edit',{'changes':changes,'previous_free_text':row['readable'] if version=='readable' and not row['mapped'] else None})
    return revision+1


def propose(rid, proposals, revision=None):
    from difflib import SequenceMatcher
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        run = con.execute('SELECT proofread,proof_revision FROM runs WHERE id=?',(rid,)).fetchone()
        if not run:
            raise ValueError('未找到版本')
        if revision is not None and run['proof_revision']!=revision:
            raise ValueError('校对期间稿件已变化，请重新生成建议')
        segments = json.loads(run['proofread']); seen = set(); checked = []
        if not isinstance(proposals,list) or len(proposals)>len(segments):
            raise ValueError('校对响应结构无效')
        for p in proposals:
            index = p['index']; after = p['text']; reason = p['reason']
            if type(index) is not int or index in seen or not 0<=index<len(segments) or not isinstance(after,str) or not isinstance(reason,str) or not reason.strip():
                raise ValueError('校对响应索引、文字或理由无效')
            seen.add(index); before = segments[index]['text']
            if before == after:
                continue
            if not after.strip() or len(after)>10000 or abs(len(after)-len(before))>max(8,int(len(before)*0.2)) or SequenceMatcher(None,before,after).ratio()<0.55:
                raise ValueError('校对建议改动过大；未应用，请人工核对')
            checked.append((uuid4().hex,rid,index,before,after,reason[:1000],1,'pending','text-only-llm'))
        con.executemany('INSERT INTO corrections(id,run_id,segment_index,before_text,after_text,reason,uncertain,state,source) VALUES(?,?,?,?,?,?,?,?,?)',checked)
        log(con,rid,'proofread','proposals',{'count':len(checked),'audio_verified':False,'state':'pending'})
    return len(checked)


def review(rid,cid,accept):
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        p = con.execute('SELECT * FROM corrections WHERE id=? AND run_id=?',(cid,rid)).fetchone()
        if not p or p['state']!='pending':
            raise ValueError('此建议已处理或不存在')
        row = con.execute('SELECT proofread FROM runs WHERE id=?',(rid,)).fetchone()
        segments = json.loads(row['proofread'])
        if accept and segments[p['segment_index']]['text'] != p['before_text']:
            raise ValueError('原片段已被修改，请重新校对')
        if accept:
            segments[p['segment_index']]['text'] = p['after_text']
            con.execute('UPDATE runs SET proofread=?,proof_revision=proof_revision+1 WHERE id=?',(json.dumps(segments,ensure_ascii=False),rid))
        con.execute('UPDATE corrections SET state=? WHERE id=?',('accepted' if accept else 'rejected',cid))
        log(con,rid,'proofread','accept' if accept else 'reject',dict(p))


def format_readable(rid, revision, remove_filler=False):
    import re
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
        if not row or row['readable_revision']!=revision:
            raise ValueError('可读稿已变化，请重新加载')
        rows = json.loads(row['proofread']); changes = []
        for i,r in enumerate(rows):
            before = r['text']
            if remove_filler:
                # Only leading hesitation interjections; never remove entire segments.
                r['text'] = re.sub(r'^(?:嗯|呃)[，,、\s]+','',r['text']) or before
            r['text'] = clean([r])
            if before != r['text']:
                changes.append({'index':i,'before':before,'after':r['text'],'start':r['start'],'end':r['end']})
        con.execute('UPDATE runs SET readable_segments=?,readable=?,readable_revision=readable_revision+1,mapped=1 WHERE id=?',(json.dumps(rows,ensure_ascii=False),clean(rows),rid))
        log(con,rid,'readable','format',{'remove_filler':remove_filler,'changes':changes,'previous_readable':row['readable'],'previous_segments':json.loads(row['readable_segments']),'source':'deterministic-rules'})
