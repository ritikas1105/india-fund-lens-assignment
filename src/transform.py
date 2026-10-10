"""Data contracts and row quarantine. Never impute a missing NAV."""
import csv
import io
import json

import numpy as np
import pandas as pd

from src.config import FUNDS

ISSUE_COLUMNS = ['scheme_code', 'severity', 'check', 'count', 'detail']


def transform(manifest, files):
    issues, funds, observations, rejected = [], [], [], []
    as_of = pd.Timestamp(manifest['extracted_at']).tz_convert('Asia/Kolkata').normalize().tz_localize(None)

    def issue(code, severity, check, count, detail):
        issues.append([code, severity, check, int(count), str(detail)])

    for err in manifest.get('errors', []):
        issue(None, 'error', 'api_failure', 1, f"{err['file']}: {err['error']}")
    for code, (label, peer) in FUNDS.items():
        filename = f'{code}.json'
        if filename not in files:
            raise ValueError(f'Missing required fund {code}; previous published dataset is preserved')
        payload = json.loads(files[filename])
        meta = payload.get('meta', {})
        if payload.get('status') != 'SUCCESS' or int(meta.get('scheme_code', -1)) != code:
            raise ValueError(f'Scheme identity/status contract failed: {code}')
        name = meta.get('scheme_name', '')
        if 'direct' not in name.lower() or 'growth' not in name.lower():
            raise ValueError(f'Expected direct growth plan: {code}, {name}')
        data = pd.DataFrame(payload.get('data', []))
        if data.empty or not {'date', 'nav'}.issubset(data.columns):
            raise ValueError(f'Empty or malformed history: {code}')
        data = data[['date', 'nav']].copy()
        data['raw_date'], data['raw_nav'] = data['date'], data['nav']
        data['date'] = pd.to_datetime(data['date'], format='%d-%m-%Y', errors='coerce')
        data['nav'] = pd.to_numeric(data['nav'], errors='coerce')
        invalid = data['date'].isna() | ~np.isfinite(data['nav']) | (data['nav'] <= 0) | (data['date'] > as_of)
        for row in data[invalid].itertuples():
            rejected.append([code, str(row.raw_date), str(row.raw_nav), 'Invalid date, future date, or nonpositive/nonfinite NAV'])
        if invalid.any():
            issue(code, 'warning', 'quarantined_rows', invalid.sum(), 'Excluded; inspect quarantine table')
        data = data[~invalid].copy()
        if data.groupby('date')['nav'].nunique().gt(1).any():
            raise ValueError(f'Conflicting NAVs on the same date: {code}')
        duplicates = data.duplicated('date').sum()
        if duplicates:
            issue(code, 'warning', 'exact_duplicates', duplicates, 'Identical observations collapsed')
        data = data.drop_duplicates('date').sort_values('date')
        if len(data) < 60 or invalid.mean() > 0.01:
            raise ValueError(f'Insufficient history or >1% rejected rows: {code}')
        gap = data['date'].diff().dt.days
        if (gap > 7).any():
            issue(code, 'warning', 'long_gap', (gap > 7).sum(), 'More than 7 calendar days between observations; no filling')
        jumps = data['nav'].pct_change(fill_method=None).abs() > 0.15
        if jumps.any():
            issue(code, 'warning', 'large_move', jumps.sum(), 'Absolute observation-to-observation return >15%; retained for review')
        age = (as_of - data['date'].max()).days
        if age > 7:
            issue(code, 'warning', 'stale_nav', age, 'Calendar days since latest NAV at extraction')
        funds.append([code, label, peer, name, meta.get('fund_house', ''), meta.get('scheme_category', ''),
                      data['date'].min().date().isoformat(), data['date'].max().date().isoformat(), len(data)])
        data['scheme_code'] = code
        observations.append(data[['scheme_code', 'date', 'nav']])
    nav = pd.concat(observations, ignore_index=True)
    fund_frame = pd.DataFrame(funds, columns=['scheme_code', 'label', 'peer_group', 'scheme_name', 'fund_house', 'category', 'first_date', 'last_date', 'observations'])
    # Missingness is relative to peers, not a naive weekday calendar that invents holiday gaps.
    wide = nav.pivot(index='date', columns='scheme_code', values='nav')
    for code in FUNDS:
        available = wide[code].dropna()
        missing = wide.loc[available.index.min():available.index.max(), code].isna().sum()
        if missing:
            issue(code, 'warning', 'peer_date_gaps', missing, 'Missing on dates where at least one other watchlist fund reports')
    checks = reconcile(files.get('amfi.txt'), nav)
    for row in checks.itertuples():
        if row.status != 'matched':
            issue(row.scheme_code, 'warning', 'amfi_reconciliation', 1, row.status)
    nav['date'] = nav['date'].dt.strftime('%Y-%m-%d')
    return {'funds': fund_frame, 'nav': nav,
            'quality': pd.DataFrame(issues, columns=ISSUE_COLUMNS),
            'quarantine': pd.DataFrame(rejected, columns=['scheme_code', 'raw_date', 'raw_nav', 'reason']),
            'reconciliation': checks}


def reconcile(text, nav):
    """Find fields by header: AMFI has changed its column layout over time."""
    records = {}
    if text:
        lines = text.splitlines()
        header = next((line for line in lines if line.startswith('Scheme Code;')), None)
        if header:
            columns = [c.strip() for c in next(csv.reader([header], delimiter=';'))]
            for row in csv.reader(io.StringIO(text), delimiter=';'):
                if len(row) != len(columns) or not row[0].strip().isdigit():
                    continue
                fields = dict(zip(columns, row))
                code = int(row[0])
                if code not in FUNDS:
                    continue
                try:
                    date = pd.to_datetime(fields['Date'], format='%d-%b-%Y')
                    value = float(fields['Net Asset Value'])
                    if np.isfinite(value) and value > 0:
                        records[code] = (date, value)
                except (ValueError, KeyError):
                    continue
    result = []
    for code in FUNDS:
        date, official = records.get(code, (pd.NaT, np.nan))
        match = nav[(nav.scheme_code == code) & (nav.date == date)]
        observed = float(match.nav.iloc[0]) if len(match) else np.nan
        if code not in records:
            status = 'official_feed_unavailable'
        elif match.empty:
            status = 'official_date_missing_in_history'
        elif abs(observed - official) <= max(0.0001, official * 0.000001):
            status = 'matched'
        else:
            status = 'value_mismatch'
        result.append([code, None if pd.isna(date) else date.date().isoformat(), official, observed, status])
    return pd.DataFrame(result, columns=['scheme_code', 'official_date', 'official_nav', 'history_nav', 'status'])
