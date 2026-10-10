"""Immutable raw snapshots, bounded retries, and checksum-verified replay."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import AMFI, API, FUNDS


def session():
    client = requests.Session()
    retry = Retry(total=3, backoff_factor=0.75, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=['GET'], respect_retry_after_header=False)
    client.mount('https://', HTTPAdapter(max_retries=retry))
    client.headers['User-Agent'] = 'IndiaFundLens/1.0 (educational data analysis)'
    return client


def extract(raw_root):
    now = datetime.now(timezone.utc)
    folder = Path(raw_root) / (now.strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    folder.mkdir(parents=True)
    manifest = {'version': 1, 'extracted_at': now.isoformat(), 'files': [], 'errors': []}
    endpoints = [(f'{code}.json', f'{API}/{code}') for code in FUNDS]
    endpoints.append(('amfi.txt', AMFI))
    with session() as client:
        for filename, url in endpoints:
            try:
                response = client.get(url, timeout=(10, 60))
                response.raise_for_status()
                content = response.content
                (folder / filename).write_bytes(content)
                manifest['files'].append({'name': filename, 'url': response.url,
                                          'sha256': hashlib.sha256(content).hexdigest(),
                                          'bytes': len(content)})
            except requests.RequestException as exc:
                manifest['errors'].append({'file': filename, 'error': str(exc)})
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return folder


def replay(folder):
    folder = Path(folder)
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version') != 1:
        raise ValueError('Unsupported raw manifest version')
    files = {}
    for entry in manifest['files']:
        name = entry['name']
        if Path(name).name != name or name in files:
            raise ValueError('Invalid or duplicate raw filename')
        content = (folder / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != entry['sha256']:
            raise ValueError(f'Checksum mismatch: {name}')
        files[name] = content.decode('utf-8-sig')
    return manifest, files
