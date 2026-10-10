"""Business-facing analytical workbench. No network calls on Streamlit reruns."""
from datetime import datetime
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

from src.analytics import compare
from src.config import DB
from src.storage import load

st.set_page_config(page_title='India Fund Lens', page_icon='◈', layout='wide')
st.markdown('''<style>
.block-container {padding-top: 2rem; max-width: 1450px;}
[data-testid="stMetric"] {background:white;border:1px solid #DCE4E8;border-radius:12px;padding:18px;}
[data-testid="stMetricLabel"] {color:#536773;}
h1 {letter-spacing:-1.6px;} .eyebrow {font-size:12px;letter-spacing:2px;color:#087F8C;font-weight:700;}
</style>''', unsafe_allow_html=True)
st.markdown('<div class="eyebrow">INDIA / MUTUAL FUND RESEARCH</div>', unsafe_allow_html=True)
st.title('Understand the journey. Not just the return.')
st.caption('India Fund Lens · Comparable NAV histories, drawdown recovery and source verification')
if not DB.exists():
    st.info('Create the local analytical dataset to begin.')
    st.code('python etl.py\n# Offline alternative, using the included dated snapshot:\npython etl.py --replay data/raw/sample')
    st.stop()


@st.cache_data(show_spinner=False)
def read_data(modified_ns):
    return load(DB)


try:
    tables, run = read_data(DB.stat().st_mtime_ns)
except Exception as exc:
    st.error(f'Cannot read the local dataset: {exc}. Rebuild it with python etl.py.')
    st.stop()
funds, nav = tables['funds'], tables['nav']
labels = funds.set_index('scheme_code')['label'].to_dict()
nav['date'] = pd.to_datetime(nav['date'])
extracted = pd.Timestamp(run['extracted_at']).tz_convert('Asia/Kolkata')
age_hours = (pd.Timestamp.now(tz='Asia/Kolkata') - extracted).total_seconds() / 3600
st.caption(f"Snapshot: {extracted:%d %b %Y, %H:%M} IST · Mode: {run['mode']} · Source: MFapi.in + AMFI")
if age_hours > 48:
    st.warning(f'This extract is {age_hours / 24:.1f} days old. Run python etl.py to refresh; charts below use the saved snapshot.')
if run['mode'] == 'replay':
    st.info('Replay mode: these are real saved source responses, not a live market feed.')

with st.sidebar:
    st.markdown('### Research scope')
    group = st.selectbox('Peer group', ['All watchlist funds'] + sorted(funds.peer_group.unique().tolist()))
    allowed = funds if group == 'All watchlist funds' else funds[funds.peer_group == group]
    codes = st.multiselect('Direct growth plans', allowed.scheme_code.tolist(), default=allowed.scheme_code.tolist(), format_func=lambda c: labels[c])
    horizon = st.selectbox('Lookback', ['3 years', '1 year', '5 years', 'Full shared history'])
    latest = nav.date.max().date()
    earliest = nav.date.min().date()
    years = {'1 year': 1, '3 years': 3, '5 years': 5}
    initial = max(earliest, (pd.Timestamp(latest) - pd.DateOffset(years=years.get(horizon, 100))).date()) if horizon in years else earliest
    date_range = st.date_input('Comparison dates', value=(initial, latest), min_value=earliest, max_value=latest, key=f'dates_{horizon}')
    amount = st.number_input('Illustrative initial value (₹)', min_value=1000, max_value=10000000, value=100000, step=10000)
    st.divider()
    st.caption('A declared six-fund index watchlist. Selection is for methodology demonstration; it is not a recommendation or the full Indian fund universe.')
    st.caption('Refresh from your terminal:')
    st.code('python etl.py', language='bash')

if not codes:
    st.info('Choose at least one fund to begin.')
    st.stop()
if len(date_range) != 2:
    st.info('Choose both a start date and an end date.')
    st.stop()
try:
    result = compare(nav, codes, *date_range)
except ValueError as exc:
    st.warning(str(exc))
    st.stop()
metrics = result['metrics'].merge(funds[['scheme_code', 'label', 'peer_group']], on='scheme_code', validate='one_to_one')
prices = result['prices']
start, end = prices.index[0], prices.index[-1]
coverage = len(prices) / result['union_dates']
a, b, c, d = st.columns(4)
a.metric('Funds in scope', len(codes))
b.metric('Shared NAV dates', f'{len(prices):,}')
c.metric('Shared-date coverage', f'{coverage:.1%}')
d.metric('Comparison ends', end.strftime('%d %b %Y'))
st.caption(f'Every chart uses {start:%d %b %Y}–{end:%d %b %Y}. {result["excluded_dates"]:,} union dates excluded because at least one selected fund has no NAV. Missing NAVs are never filled.')
if coverage < .98:
    st.warning('Shared-date coverage is below 98%. Review gaps in Data trust before drawing conclusions.')
if (pd.Timestamp(datetime.now(ZoneInfo('Asia/Kolkata')).date()) - end).days > 7:
    st.warning('The comparison ends more than 7 calendar days ago. Check the requested range and source freshness.')
if metrics.peer_group.nunique() > 1:
    st.caption('Multiple index mandates selected. Differences reflect index exposure as well as fund implementation; use the peer-group filter for closer comparisons.')


def chart_frame(frame, value):
    long = frame.rename_axis('date').reset_index().melt('date', var_name='scheme_code', value_name=value)
    long['Fund'] = long.scheme_code.map(labels)
    return long


def line_chart(frame, value, title, percent=False):
    chart = alt.Chart(chart_frame(frame, value)).mark_line(strokeWidth=2).encode(
        x=alt.X('date:T', title=None),
        y=alt.Y(f'{value}:Q', title=title, scale=alt.Scale(zero=False), axis=alt.Axis(format='.0%' if percent else ',.0f')),
        color=alt.Color('Fund:N', scale=alt.Scale(scheme='tableau10'), legend=alt.Legend(orient='bottom')),
        tooltip=[alt.Tooltip('date:T', title='Date'), 'Fund:N', alt.Tooltip(f'{value}:Q', format='.2%' if percent else ',.2f')]
    ).properties(height=340).interactive()
    st.altair_chart(chart, use_container_width=True)


def display_metrics(frame):
    display = frame[['label', 'period_return', 'cagr', 'annualized_volatility', 'max_drawdown', 'current_drawdown', 'worst_episode_days', 'recovery_status']].copy()
    display.columns = ['Fund', 'Period return', 'CAGR', 'Annualized volatility', 'Max drawdown', 'Current drawdown', 'Worst episode days', 'Recovery']
    for column in ['Period return', 'CAGR', 'Annualized volatility', 'Max drawdown', 'Current drawdown']:
        display[column] = display[column].map(lambda value: '—' if pd.isna(value) else f'{value:.2%}')
    st.dataframe(display, hide_index=True, use_container_width=True)


overview, recovery, relationships, trust, methodology = st.tabs(['Performance', 'Drawdown & recovery', 'Co-movement', 'Data trust', 'Methodology'])
with overview:
    st.subheader('One starting value. The same dates.')
    st.caption('Illustrative lump-sum NAV growth; no contributions, withdrawals, taxes or exit loads.')
    line_chart(result['indexed'] * amount / 100, 'Value', 'Illustrative value (₹)')
    display_metrics(metrics)
    st.caption('CAGR is withheld for periods shorter than one year. Volatility uses 252 observations/year and excludes returns spanning more than four calendar days.')
    st.download_button('Download comparison CSV', metrics.to_csv(index=False).encode(), 'fund_comparison.csv', 'text/csv')
with recovery:
    st.subheader('How deep was the decline—and how long did it last?')
    line_chart(result['drawdown'], 'Drawdown', 'Decline from observed running peak', percent=True)
    episodes = metrics[['label', 'peak_date', 'trough_date', 'recovery_date', 'worst_episode_days', 'recovery_status']].copy()
    episodes.columns = ['Fund', 'Peak', 'Trough', 'Recovered on', 'Elapsed calendar days', 'Status']
    st.dataframe(episodes, hide_index=True, use_container_width=True)
    st.info('Ongoing episodes end at the last shared observation. Their final recovery time is unknown. Drawdowns start at the beginning of the selected window; earlier peaks are outside scope.')
with relationships:
    st.subheader('Different fund names can move together')
    st.caption('Correlation measures NAV-return co-movement, not holdings overlap, and does not establish future diversification.')
    if len(codes) < 2:
        st.info('Select at least two funds to compare co-movement.')
    else:
        corr = result['correlation'].rename(index=labels, columns=labels)
        tidy = corr.rename_axis('Fund A').reset_index().melt('Fund A', var_name='Fund B', value_name='Correlation')
        heatmap = alt.Chart(tidy).mark_rect().encode(
            x=alt.X('Fund B:N', title=None, axis=alt.Axis(labelAngle=-30)), y=alt.Y('Fund A:N', title=None),
            color=alt.Color('Correlation:Q', scale=alt.Scale(domain=[-1, 1], scheme='redblue')),
            tooltip=['Fund A:N', 'Fund B:N', alt.Tooltip('Correlation:Q', format='.3f')]).properties(height=350)
        st.altair_chart(heatmap, use_container_width=True)
        st.caption(f'{len(result["returns"])} eligible shared return intervals; at least 60 required for each correlation. {result["long_intervals_excluded"]} long intervals excluded.')
with trust:
    st.subheader('Trace the numbers back to their sources')
    st.markdown('**AMFI reconciliation** compares exact scheme codes and exact dates. A newer official NAV absent from history is a lag, not a price mismatch.')
    reconciliation = tables['reconciliation'].merge(funds[['scheme_code', 'label']], on='scheme_code')
    st.dataframe(reconciliation, hide_index=True, use_container_width=True)
    quality = tables['quality']
    st.markdown(f'**{len(quality)} quality findings across the full watchlist**')
    if quality.empty:
        st.success('No quality findings recorded for this snapshot.')
    else:
        st.dataframe(quality, hide_index=True, use_container_width=True)
    with st.expander('Source lineage and run manifest'):
        st.json(run)
    with st.expander('Quarantined records'):
        st.dataframe(tables['quarantine'], hide_index=True, use_container_width=True)
    st.download_button('Download quality report', quality.to_csv(index=False).encode(), 'quality_report.csv', 'text/csv')
with methodology:
    st.markdown('''
**Decision supported:** review comparable passive equity fund histories and identify data issues before interpreting performance.

- **Universe:** six manually declared direct-growth index plans, grouped by index mandate. No automated winner ranking.
- **Alignment:** intersection of actual reported NAV dates for the selected schemes and range. No price interpolation, forward fill, or manufactured trading calendar.
- **Return:** final NAV / initial NAV − 1. CAGR uses actual calendar days / 365.25, with a minimum one-year horizon.
- **Drawdown:** NAV / running maximum − 1. Worst-episode duration runs from its preceding peak to the first observed recovery, or to the final observation when ongoing.
- **Volatility:** sample standard deviation of common-interval returns × √252. Intervals longer than four calendar days are omitted. This is an approximation, not a holiday-calendar model.
- **Correlation:** Pearson correlation of those same eligible returns, with at least 60 observations.
- **Trust:** raw SHA-256 checksums, plan identity checks, duplicate checks, quarantine, stale-data and gap warnings, and same-date AMFI reconciliation.

These are retrospective NAV analytics, not investment advice or forecasts. NAVs do not reveal holdings overlap or investor-specific after-tax returns. A selected surviving-fund watchlist carries selection and survivorship bias.
''')
    st.markdown('[MFapi API documentation](https://www.mfapi.in/docs/) · [AMFI official NAV](https://www.amfiindia.com/net-asset-value)')
st.divider()
st.caption('Data: MFapi.in historical NAV API and Association of Mutual Funds in India (AMFI). Research demonstration; source availability and historical revisions can affect results.')
