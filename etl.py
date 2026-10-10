"""Usage: python etl.py [--replay data/raw/sample]"""
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.config import DB, ROOT
from src.extract import extract, replay
from src.storage import publish
from src.transform import transform


def run(raw_dir=None, destination=DB):
    folder = Path(raw_dir) if raw_dir else extract(ROOT / 'data' / 'raw')
    logging.info('Raw snapshot: %s', folder)
    manifest, files = replay(folder)
    tables = transform(manifest, files)
    metadata = {'schema_version': 1, 'extracted_at': manifest['extracted_at'],
                'built_at': datetime.now(timezone.utc).isoformat(), 'mode': 'replay' if raw_dir else 'live',
                'snapshot': folder.name, 'sources': manifest['files'], 'errors': manifest.get('errors', [])}
    publish(tables, metadata, destination)
    logging.info('Published %s NAV rows, %s funds, %s quality findings to %s',
                 len(tables['nav']), len(tables['funds']), len(tables['quality']), destination)
    return tables, metadata


def main():
    parser = argparse.ArgumentParser(description='Extract, validate, reconcile and atomically publish Indian fund NAVs.')
    parser.add_argument('--replay', type=Path, help='Replay a saved raw snapshot without network access')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        run(args.replay)
    except Exception as exc:
        logging.error('Run failed; previous published data preserved: %s', exc)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
