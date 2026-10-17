"""Check tracked release files without reading private runtime directories."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = {'data', '.venv', 'node_modules', '.next', '__pycache__', '.git'}
SECRET = re.compile(rb'(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')


def problems(name, content):
    path = Path(name)
    found = []
    if PRIVATE.intersection(path.parts) or path.name.startswith('.env') or path.suffix in ('.sqlite3', '.db', '.pem', '.key') or path.name == 'llm-settings.json':
        found.append('private runtime/config file')
    if SECRET.search(content):
        found.append('possible credential (value redacted)')
    if len(content) > 25 * 1024 * 1024:
        found.append('unexpected file over 25 MB')
    return found


def main():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    failures = []
    for name in filter(None, names):
        path = ROOT / name
        if path.is_symlink():
            failures.append((name, ['symlink requires manual review']))
            continue
        failures.extend((name, [problem]) for problem in problems(name, path.read_bytes()))
    for name, details in failures:
        print(name + ': ' + ', '.join(details))
    if not any(names):
        print('No tracked files: stage the intended release files first.')
        return 1
    print(f'Release file check: {len(list(filter(None, names)))} files; {len(failures)} problems. Manual review is also required.')
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main())
