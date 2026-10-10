import copy
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from etl import run
from src.config import FUNDS, ROOT
from src.extract import replay
from src.storage import load, publish
from src.transform import reconcile, transform


@pytest.fixture
def raw():
    return replay(ROOT / 'data/raw/sample')


def edit(raw, function):
    manifest, files = copy.deepcopy(raw)
    name = f'{next(iter(FUNDS))}.json'
    payload = json.loads(files[name])
    function(payload)
    files[name] = json.dumps(payload)
    return manifest, files


def test_real_snapshot_contracts_and_keys(raw):
    tables = transform(*raw)
    assert len(tables['funds']) == 6
    assert not tables['nav'].duplicated(['scheme_code', 'date']).any()
    assert tables['nav'].nav.gt(0).all()
    assert set(tables['nav'].scheme_code) == set(FUNDS)


def test_invalid_nav_quarantined(raw):
    changed = edit(raw, lambda p: p['data'][0].update(nav='NaN'))
    tables = transform(*changed)
    assert len(tables['quarantine']) == 1
    assert 'quarantined_rows' in tables['quality']['check'].tolist()


def test_future_date_quarantined(raw):
    changed = edit(raw, lambda p: p['data'][0].update(date='01-01-2099'))
    assert len(transform(*changed)['quarantine']) == 1


def test_conflicting_duplicates_block_publication(raw):
    def mutate(payload):
        row = dict(payload['data'][0])
        row['nav'] = str(float(row['nav']) + 1)
        payload['data'].append(row)
    with pytest.raises(ValueError, match='Conflicting NAVs'):
        transform(*edit(raw, mutate))


def test_exact_duplicate_is_deduplicated(raw):
    changed = edit(raw, lambda p: p['data'].append(dict(p['data'][0])))
    result = transform(*changed)
    assert 'exact_duplicates' in result['quality']['check'].tolist()
    assert not result['nav'].duplicated(['scheme_code', 'date']).any()


def test_wrong_scheme_identity_fails(raw):
    with pytest.raises(ValueError, match='identity'):
        transform(*edit(raw, lambda p: p['meta'].update(scheme_code=0)))


def test_wrong_plan_fails(raw):
    with pytest.raises(ValueError, match='direct growth'):
        transform(*edit(raw, lambda p: p['meta'].update(scheme_name='Regular Dividend')))


def test_missing_required_fund_fails(raw):
    manifest, files = copy.deepcopy(raw)
    del files[f'{next(iter(FUNDS))}.json']
    with pytest.raises(ValueError, match='Missing required'):
        transform(manifest, files)


def test_official_feed_is_optional_but_visible(raw):
    manifest, files = copy.deepcopy(raw)
    del files['amfi.txt']
    result = transform(manifest, files)
    assert set(result['reconciliation'].status) == {'official_feed_unavailable'}


@pytest.mark.parametrize('layout', ['old', 'new'])
def test_amfi_parser_supports_column_layout_changes(layout):
    code = next(iter(FUNDS))
    if layout == 'old':
        text = f'Scheme Code;Scheme Name;Net Asset Value;Date\n{code};Fund;100.0;02-Jan-2024'
    else:
        text = f'Scheme Code;ISIN Div Payout/ ISIN Growth;Scheme Name;Plan;Option;Net Asset Value;Date\n{code};XYZ;Fund;Direct;Growth;100.0;02-Jan-2024'
    nav = pd.DataFrame({'scheme_code': [code], 'date': [pd.Timestamp('2024-01-02')], 'nav': [100.]})
    assert reconcile(text, nav).iloc[0].status == 'matched'
    nav.loc[0, 'nav'] = 99
    assert reconcile(text, nav).iloc[0].status == 'value_mismatch'
    nav.loc[0, 'date'] = pd.Timestamp('2024-01-01')
    assert reconcile(text, nav).iloc[0].status == 'official_date_missing_in_history'


def test_tampered_replay_is_rejected(tmp_path):
    content = b'original'
    manifest = {'version': 1, 'files': [{'name': 'test.json', 'sha256': hashlib.sha256(content).hexdigest()}]}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    (tmp_path / 'test.json').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='Checksum mismatch'):
        replay(tmp_path)


def test_failed_refresh_preserves_previous_database(raw, tmp_path):
    tables = transform(*raw)
    destination = tmp_path / 'test.sqlite'
    publish(tables, {'test': True}, destination)
    before = destination.read_bytes()
    broken = dict(tables)
    broken['nav'] = pd.concat([tables['nav'], tables['nav'].iloc[:1]])
    with pytest.raises(Exception):
        publish(broken, {}, destination)
    assert destination.read_bytes() == before
    assert not list(tmp_path.glob('build-*'))


def test_replay_is_idempotent(tmp_path):
    destination = tmp_path / 'data.sqlite'
    run(ROOT / 'data/raw/sample', destination)
    first, _ = load(destination)
    run(ROOT / 'data/raw/sample', destination)
    second, meta = load(destination)
    pd.testing.assert_frame_equal(first['nav'], second['nav'])
    assert meta['mode'] == 'replay'
