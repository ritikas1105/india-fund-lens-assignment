import numpy as np
import pandas as pd
import pytest

from src.analytics import compare


def history(values, code=1):
    return pd.DataFrame({'scheme_code': code, 'date': pd.bdate_range('2024-01-01', periods=len(values)), 'nav': values})


def calculate(data, codes=None):
    return compare(data, codes or [1], data.date.min(), data.date.max())


def test_known_return_and_drawdown():
    values = [100] * 20 + [80] * 20 + [120] * 30
    result = calculate(history(values))
    metric = result['metrics'].iloc[0]
    assert metric.period_return == pytest.approx(.2)
    assert metric.max_drawdown == pytest.approx(-.2)
    assert metric.current_drawdown == 0
    assert metric.recovery_status == 'Recovered'
    assert pd.isna(metric.cagr)  # Do not annualize short history.


def test_unrecovered_drawdown_is_right_censored():
    data = history([100] * 10 + [75] * 60)
    metric = calculate(data)['metrics'].iloc[0]
    assert metric.recovery_status == 'Ongoing'
    assert metric.recovery_date is None
    assert metric.max_drawdown == -.25


def test_shared_dates_never_fill_missing_values():
    first = history(np.arange(100, 180))
    second = history(np.arange(200, 280), 2).drop(index=[0, 10, 20])
    result = calculate(pd.concat([first, second]), [1, 2])
    assert result['excluded_dates'] == 3
    assert len(result['prices']) == 77
    assert result['indexed'].iloc[0].tolist() == [100., 100.]
    assert first.date.iloc[10] not in result['prices'].index


def test_insufficient_shared_history_is_rejected():
    with pytest.raises(ValueError, match='60 shared'):
        calculate(history([100] * 59))


def test_calendar_day_cagr():
    data = history(np.linspace(100, 150, 400))
    metric = calculate(data)['metrics'].iloc[0]
    days = (data.date.max() - data.date.min()).days
    assert metric.cagr == pytest.approx(1.5 ** (365.25 / days) - 1)


def test_long_intervals_excluded_from_volatility():
    data = history(np.arange(100, 190)).drop(index=range(30, 40))
    result = calculate(data)
    assert result['long_intervals_excluded'] == 1
    assert len(result['returns']) == len(data) - 2


def test_no_decline_has_zero_drawdown_duration():
    metric = calculate(history(np.arange(100, 180)))['metrics'].iloc[0]
    assert metric.max_drawdown == 0
    assert metric.worst_episode_days == 0


def test_duration_starts_at_last_equal_peak():
    data = history([100] * 20 + [80] * 20 + [120] * 30)
    metric = calculate(data)['metrics'].iloc[0]
    assert metric.peak_date == data.date.iloc[19].date().isoformat()
    assert metric.worst_episode_days == (data.date.iloc[40] - data.date.iloc[19]).days
