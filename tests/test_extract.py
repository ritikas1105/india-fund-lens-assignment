import json

import pytest
import requests

from src import extract
from src.config import FUNDS


def test_http_failures_are_recorded_and_raw_successes_preserved(tmp_path, monkeypatch):
    class Response:
        content = b'{"data": []}'
        url = 'https://example.test/nav'

        def raise_for_status(self):
            return None

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, timeout):
            if url.endswith(str(next(iter(FUNDS)))):
                raise requests.Timeout('simulated timeout')
            return Response()

    monkeypatch.setattr(extract, 'session', Client)
    folder = extract.extract(tmp_path)
    manifest, files = extract.replay(folder)
    assert len(manifest['errors']) == 1
    assert 'simulated timeout' in manifest['errors'][0]['error']
    assert len(files) == len(FUNDS)  # Five funds plus optional AMFI response.


def test_retry_policy_is_bounded_and_only_safe_methods():
    with extract.session() as client:
        policy = client.get_adapter('https://').max_retries
        assert policy.total == 3
        assert policy.allowed_methods == ['GET']
        assert 429 in policy.status_forcelist
        assert 503 in policy.status_forcelist
