from streamlit.testing.v1 import AppTest
from src.config import ROOT
from src import config
from etl import run


def test_dashboard_default_and_filters(tmp_path, monkeypatch):
    destination = tmp_path / 'app.sqlite'
    run(ROOT / 'data/raw/sample', destination)
    monkeypatch.setattr(config, 'DB', destination)
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
    assert not app.exception
    assert len(app.tabs) == 5
    assert app.metric[0].value == '6'
    app.sidebar.selectbox[0].select('Nifty 50').run()
    assert not app.exception
    assert app.metric[0].value == '3'
    app.sidebar.multiselect[0].set_value([]).run()
    assert not app.exception
    assert any('Choose at least one' in x.value for x in app.info)
