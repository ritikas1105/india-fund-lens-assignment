"""Comparisons use identical observation dates and do not forward-fill prices."""
import numpy as np
import pandas as pd


def compare(nav, codes, start, end):
    chosen = nav[nav.scheme_code.isin(codes)].copy()
    chosen['date'] = pd.to_datetime(chosen['date'])
    chosen = chosen[chosen.date.between(pd.Timestamp(start), pd.Timestamp(end))]
    wide = chosen.pivot(index='date', columns='scheme_code', values='nav').reindex(columns=codes).sort_index()
    shared = wide.dropna(how='any')
    if len(shared) < 60:
        raise ValueError('Select a longer period or fewer funds: at least 60 shared NAV dates are required.')
    indexed = shared.div(shared.iloc[0]).mul(100)
    drawdown = shared.div(shared.cummax()).sub(1)
    returns = shared.pct_change(fill_method=None)
    # Long data outages are not treated as one-day returns for annualized volatility/correlation.
    eligible = shared.index.to_series().diff().dt.days.le(4)
    returns = returns.loc[eligible]
    days = (shared.index[-1] - shared.index[0]).days
    rows = []
    for code in codes:
        total = shared[code].iloc[-1] / shared[code].iloc[0] - 1
        cagr = (1 + total) ** (365.25 / days) - 1 if days >= 365 else np.nan
        dd = drawdown[code]
        trough = dd.idxmin()
        # Use the most recent equal peak before the decline, not an older plateau.
        peak = shared.loc[:trough, code].iloc[::-1].idxmax()
        recovery = shared.loc[trough:, code]
        recovered = recovery[recovery >= shared.loc[peak, code]]
        recovery_date = recovered.index[0] if len(recovered) else pd.NaT
        underwater_days = ((recovery_date if pd.notna(recovery_date) else shared.index[-1]) - peak).days
        rows.append([code, total, cagr, returns[code].std(ddof=1) * np.sqrt(252), dd.min(), dd.iloc[-1],
                     underwater_days, 'Recovered' if pd.notna(recovery_date) else 'Ongoing',
                     peak.date().isoformat(), trough.date().isoformat(),
                     None if pd.isna(recovery_date) else recovery_date.date().isoformat(),
                     wide[code].notna().sum() / len(wide)])
    metrics = pd.DataFrame(rows, columns=['scheme_code', 'period_return', 'cagr', 'annualized_volatility', 'max_drawdown',
                                          'current_drawdown', 'worst_episode_days', 'recovery_status', 'peak_date',
                                          'trough_date', 'recovery_date', 'coverage'])
    return {'prices': shared, 'indexed': indexed, 'drawdown': drawdown, 'returns': returns,
            'correlation': returns.corr(min_periods=60), 'metrics': metrics,
            'excluded_dates': len(wide) - len(shared), 'union_dates': len(wide),
            'long_intervals_excluded': int((~eligible.iloc[1:]).sum())}
