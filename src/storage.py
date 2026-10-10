"""Publish an entire validated run with one atomic filesystem replacement."""
import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd


def publish(tables, metadata, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='build-', suffix='.sqlite', dir=destination.parent)
    os.close(fd)
    try:
        with sqlite3.connect(temporary) as connection:
            for name, frame in tables.items():
                frame.to_sql(name, connection, index=False, if_exists='fail')
            connection.execute('CREATE UNIQUE INDEX nav_key ON nav(scheme_code, date)')
            connection.execute('CREATE UNIQUE INDEX fund_key ON funds(scheme_code)')
            orphans = connection.execute('SELECT COUNT(*) FROM nav n LEFT JOIN funds f USING(scheme_code) WHERE f.scheme_code IS NULL').fetchone()[0]
            if orphans:
                raise ValueError('Orphan NAV records')
            connection.execute('CREATE TABLE run (metadata TEXT NOT NULL)')
            connection.execute('INSERT INTO run VALUES (?)', (json.dumps(metadata),))
            if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite integrity check failed')
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load(destination):
    with sqlite3.connect(f'{Path(destination).resolve().as_uri()}?mode=ro', uri=True) as connection:
        tables = {name: pd.read_sql_query(f'SELECT * FROM {name}', connection)
                  for name in ['funds', 'nav', 'quality', 'quarantine', 'reconciliation']}
        metadata = json.loads(connection.execute('SELECT metadata FROM run').fetchone()[0])
    return tables, metadata
