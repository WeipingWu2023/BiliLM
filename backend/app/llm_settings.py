"""Local provider settings. Public responses never contain the API key."""
import json
import os
from uuid import uuid4
from . import db

DEEPSEEK_URL='https://api.deepseek.com'
DEFAULT_MODEL='deepseek-flash'


def load():
    path=db.DATA/'llm-settings.json'
    if path.is_file():
        return json.loads(path.read_text(encoding='utf-8'))
    return {'url':os.getenv('BILILM_LLM_URL',''),'model':os.getenv('BILILM_LLM_MODEL','local'),
            'key':os.getenv('BILILM_LLM_KEY','')}


def public():
    value=load()
    return {'configured':bool(value['url']),'provider':'deepseek' if value['url']==DEEPSEEK_URL else 'compatible',
            'model':value['model'] if value['url'] else DEFAULT_MODEL,'key_saved':bool(value['key']),
            'auto_enabled':bool(value.get('auto_enabled',False))}


def save_deepseek(key,model):
    old=load()
    key=key.strip() or (old['key'] if old['url']==DEEPSEEK_URL else '')
    if not key or any(c.isspace() for c in key):
        raise ValueError('请填写有效 DeepSeek API Key；密钥不应包含空格或换行')
    db.DATA.mkdir(parents=True,exist_ok=True)
    temp=db.DATA/('llm-settings-'+uuid4().hex+'.tmp')
    try:
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as file:
            json.dump({'url':DEEPSEEK_URL,'model':model,'key':key,'auto_enabled':True},file)
        temp.replace(db.DATA/'llm-settings.json')
    finally:
        temp.unlink(missing_ok=True)
    return public()
