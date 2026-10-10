# Simulated Architecture and Implementation Conversation


**Senior Data Engineer:** I want to build a local research application with Python and Streamlit. The business problem is fund comparability: people compare returns without checking whether the observation windows match or what happened between the endpoints. I want the analyst to examine returns, drawdowns, recovery time, and confidence in the underlying data.

Keep the first release focused on Indian passive equity funds. It should help someone review evidence, not recommend an investment. Before implementation, compare suitable public sources. I care about historical depth, source authority, authentication, failure behavior, and integration effort.

**AI Coding Assistant:** I would consider these options:

| Candidate | Advantages | Disadvantages and reliability considerations | Access and integration |
|---|---|---|---|
| MFapi.in | Indian mutual-fund metadata and NAV histories, with scheme identifiers and straightforward JSON | Historical completeness and freshness still require validation; do not interpret website uptime claims as an independently verified SLA | Keyless. Documentation says rate limiting applies and recommends caching, while the homepage says no rate limiting. Treat the quota as unspecified and handle throttling. Low integration complexity. |
| AMFI NAV feed | Official NAV publication from the Indian industry association; useful for checking scheme/date/value agreement | The current feed is not a full historical series. Delimited records and section headings need defensive parsing. A separate publisher endpoint is not proof of independently generated underlying data | Public downloadable text feed, no key in the configured URL. No numeric request quota established by this review. Moderate parser complexity. |
| Alpha Vantage | Broader financial-data API worth considering for a different market-data application | We have not established coverage of this exact Indian mutual-fund universe. Adding it would require a coverage proof and another data contract | Requires an API key. Its support page describes 25 free requests/day, with exceptions for verified educational/open-source projects; eligibility cannot be assumed. Not integrated in this repository. |

The provider access statements are from [MFapi documentation](https://www.mfapi.in/docs/), the [MFapi homepage](https://www.mfapi.in/), [AMFI's NAV portal](https://www.amfiindia.com/net-asset-value), and [Alpha Vantage support](https://www.alphavantage.co/support/). Product-fit assessments are engineering judgments, not measured service guarantees.

**Senior Data Engineer:** Choose MFapi for history and AMFI for reconciliation. I don't want credentials in the reviewer's setup, and the broader provider adds no demonstrated value for this watchlist. Be precise in the documentation: AMFI is an industry association, not a government agency, and its text download is not a JSON API.

I also don't want us to call two feeds independent proof of correctness if they may share upstream publication data. Treat AMFI as a cross-source consistency check.

**AI Coding Assistant:** That matches the configured endpoints:

```python
API = 'https://api.mfapi.in/mf'
AMFI = 'https://portal.amfiindia.com/spages/NAVAll.txt'
```

The extractor requests one historical response for each configured scheme and one AMFI response. The application does not integrate Alpha Vantage, a trading API, holdings data, or an index benchmark feed.

**Senior Data Engineer:** Define a small declared universe rather than searching dynamically for the best-performing funds. Use the three Nifty 50 plans from HDFC, UTI, and Bandhan, two Nifty Next 50 plans from ICICI and UTI, and DSP's Nifty 50 Equal Weight plan. Group them by mandate.

An all-fund view is useful, but index exposure should not be mistaken for manager skill. Include period return, CAGR, annualized volatility, maximum and current drawdown, recovery status, and return correlation. No alpha or tracking error without the relevant benchmark series.

My acceptance criteria are: a reviewer can run the standard Python setup locally; extraction retains inspectable raw data; comparisons use common dates; failed refreshes preserve the published dataset; trust findings are visible; and calculations have meaningful tests. No cloud service or external database should be required.

**AI Coding Assistant:** The watchlist in `src/config.py` uses six scheme codes as keys. Display labels and peer groups are declared there; full names, fund houses, and categories come from source metadata. Selection and survivorship bias remain limitations of that universe.

For the UI, I suggest five views: Performance, Drawdown & recovery, Co-movement, Data trust, and Methodology. An initial-value input can scale each series to an illustrative rupee amount without pretending to model a real investor account.

**Senior Data Engineer:** Use those views. The monetary chart must say it excludes contributions, withdrawals, taxes, and exit loads. Keep the methodology beside the charts. Now separate ingestion from rendering; changing a Streamlit filter must not send another API request.

**AI Coding Assistant:** The implementation separates those responsibilities:

```text
etl.py
  extract → saved response files + manifest
  replay → checksum verification + decoding
  transform → contracts + quarantine + reconciliation
  publish → complete SQLite snapshot

app.py
  read-only SQLite load → selected shared-date analytics → charts / CSV exports
```

`src/extract.py`, `src/transform.py`, `src/storage.py`, and `src/analytics.py` contain the supporting logic. The app caches database loading using its modification time as an argument. All dashboard calculations use local data.

**Senior Data Engineer:** Why SQLite rather than Parquet? And don't introduce a generic ingestion framework for two sources.

**AI Coding Assistant:** Parquet would be reasonable for analytical columns, but this application benefits from packaging six related tables into one replaceable file. SQLite is included with Python, supports unique indexes, and needs no service. The published tables are `funds`, `nav`, `quality`, `quarantine`, `reconciliation`, and `run`.

The implementation uses pandas for transformations and interactive calculations rather than pushing analytics into SQL. That's practical for this watchlist. It is not a demonstrated design for millions of rows or many concurrent users.

**Senior Data Engineer:** Agreed. Preserve module boundaries so the storage strategy can change later. For scalability, I want a credible migration path, not a claim that this local release is production-scale. Start with sequential requests and full-history refreshes; six funds don't justify distributed execution.

**AI Coding Assistant:** Full-history refreshes also pick up retrospective source revisions. The tradeoff is repeated transfer and processing. Expanding to thousands of funds would require quota-aware scheduling, incremental requests with a revision lookback, retention rules, and more selective analytical reads. Those are future changes; the repository currently has no scheduler, concurrent-writer lock, incremental loader, or retention job.

**Senior Data Engineer:** Let's define extraction behavior. Save successful response bytes before interpreting their contents. Use unique run folders, record URLs and checksums, and make offline replay explicit. Don't automatically substitute an old sample when the live request fails.

**AI Coding Assistant:** `extract()` creates a UTC timestamp plus random suffix for the run directory. Each successful response is persisted with a SHA-256 digest, response URL, and byte count in `manifest.json`. Request exceptions are recorded in the manifest. The run timestamp is captured at extraction start; it is not a separate fetch time for every response.

Live runs and offline runs both pass through `replay()`, which verifies manifest version, filenames, and checksums before decoding. The explicit offline command is:

```bash
python etl.py --replay data/raw/sample
```

These are retained snapshots by application convention, not filesystem-enforced immutable storage. Hashes detect response changes relative to the manifest; they do not authenticate a manifest an attacker can also modify.

**Senior Data Engineer:** Show the retry policy. I want finite retries and timeouts, but avoid describing them as an end-to-end deadline.

**AI Coding Assistant:** The implemented policy is:

```python
retry = Retry(total=3, backoff_factor=0.75,
              status_forcelist=[429, 500, 502, 503, 504],
              allowed_methods=['GET'], respect_retry_after_header=False)
```

Requests use `timeout=(10, 60)`. That sets connection and read timeouts; it is not a total wall-clock limit for the whole pipeline. `total=3` permits up to three retries after an initial attempt. Requests are sequential and use an HTTPS session adapter.

**Senior Data Engineer:** Disabling `Retry-After` needs to be called out. It bounds reliance on server-provided waits, but it can retry earlier than the provider requests. We should eventually honor a capped delay within a run budget. Don't imply that behavior exists already.

Also, are all error bodies retained?

**AI Coding Assistant:** No. `raise_for_status()` runs before writing response bytes. Successful HTTP responses with malformed JSON are saved, but HTTP-error bodies are not retained; their exceptions are logged in the manifest. Capped `Retry-After` handling and error-body capture remain improvements.

**Senior Data Engineer:** Now the publication policy. I prefer availability, so could we publish five funds when the sixth fails?

**AI Coding Assistant:** That is possible in a different design, but the current six-fund universe is part of the comparison contract. Quietly publishing five changes the research scope. Mixing a stale sixth history into a fresh run would also create mixed provenance unless explicitly modeled.

**Senior Data Engineer:** Fair objection. Require all six historical responses for this release. If one is missing, preserve the previous complete dataset. AMFI is different: losing the cross-check should make the dataset unverified, not unusable. Never hide that distinction.

**AI Coding Assistant:** That is the implemented policy. A missing required history raises a `ValueError`. An absent or unusable AMFI record becomes `official_feed_unavailable`, with a quality warning. An extraction error for AMFI is also retained as an `api_failure` finding when transformation can otherwise complete.

There is a nuance: “optional AMFI” does not mean every possible exception in its processing is isolated. For example, decoding invalid bytes happens during replay and can fail the run. The optional-feed test covers a missing feed, not arbitrary corruption in every form.

**Senior Data Engineer:** Keep that limitation in the review. For NAV rows, enforce positive finite values and explicit date parsing. Invalid rows should be inspectable, but a badly damaged fund must fail the refresh.

**AI Coding Assistant:** `transform()` checks a successful source status, expected scheme code, and a name containing “direct” and “growth.” It parses dates with `%d-%m-%Y`, converts NAVs to numeric values, and rejects invalid dates, future dates, nonfinite NAVs, and NAVs at or below zero. “Future” is relative to the extraction-start date in Asia/Kolkata, making replay stable across later runs.

Rejected raw date/value pairs become quarantine rows. Publication is blocked if a fund has fewer than 60 valid observations or more than 1% invalid source rows. If the run fails, its original raw files remain available, but the partially built quarantine table is not published to replace the previous database.

**Senior Data Engineer:** Separate duplicate cases. An exact repeated observation is different from two conflicting values. Sorting and keeping the last row is not a defensible conflict-resolution policy here.

**AI Coding Assistant:** The implementation does precisely that:

```python
if data.groupby('date')['nav'].nunique().gt(1).any():
    raise ValueError(f'Conflicting NAVs on the same date: {code}')
```

After that check, identical dates can be deduplicated with a warning. It also warns about gaps longer than seven calendar days, absolute observation-to-observation returns over 15%, and a latest NAV older than seven days at extraction. These conditions retain the observations rather than automatically deleting potentially real market moves.

**Senior Data Engineer:** Do not flag every missing weekday as bad data. Holidays and scheme lifecycles complicate that. How are missing dates evaluated?

**AI Coding Assistant:** The transform compares each fund against dates reported by at least one watchlist peer, bounded by that fund's first and last observations. Missing peer dates generate findings. It is an approximation, not a holiday-calendar implementation or proof that the source should have reported on every such date.

**Senior Data Engineer:** For analytics, I initially considered forward-filling isolated missing NAVs. It would keep the chart continuous. What would that do to the metrics?

**AI Coding Assistant:** It can introduce artificial zero returns followed by larger catch-up returns, affecting volatility and correlation. The current implementation uses the intersection of reported dates instead:

```python
wide = chosen.pivot(index='date', columns='scheme_code', values='nav').reindex(columns=codes).sort_index()
shared = wide.dropna(how='any')
if len(shared) < 60:
    raise ValueError('Select a longer period or fewer funds: at least 60 shared NAV dates are required.')
indexed = shared.div(shared.iloc[0]).mul(100)
drawdown = shared.div(shared.cummax()).sub(1)
```

That sacrifices some observations, but keeps endpoints and return intervals consistent across the selection.

**Senior Data Engineer:** Use the intersection, then show the actual common start and end dates and how many union dates were excluded. Warn below 98% shared coverage. Make it clear that adding a fund can change the comparison window and even the observed worst drawdown.

For CAGR, use elapsed calendar days and withhold it below one year. I don't want a short burst annualized into an impressive-looking number.

**AI Coding Assistant:** CAGR is `(last / first) ** (365.25 / elapsed_days) - 1`, computed only for at least 365 elapsed days. Period return is `last / first - 1`. Shared-date coverage is the shared count divided by the selected union count.

Volatility uses sample standard deviation of percentage returns multiplied by `sqrt(252)`. Return intervals longer than four calendar days are removed from volatility and correlation, while the price and drawdown curves retain all shared observations.

**Senior Data Engineer:** Four days is a heuristic. It may discard a legitimate extended holiday return, and remaining intervals aren't uniformly one calendar day. Label the result as an annualization approximation. Also, 60 price observations produce at most 59 returns, so don't claim 60 prices guarantee a correlation estimate.

**AI Coding Assistant:** Correct. The code separately calls `returns.corr(min_periods=60)`. A selection can pass the price-count gate while correlation remains undefined. Constant return series can also give undefined correlation. Neither case should be interpreted as zero correlation. The existing tests do not directly assert both of those correlation edge cases.

**Senior Data Engineer:** Drawdown recovery needs careful semantics. Report calendar days from the preceding peak to the first observed return to that level. If recovery hasn't occurred, show “Ongoing” and no recovery date. Don't pass the final observation off as recovery.

**AI Coding Assistant:** The code implements an ongoing episode's elapsed duration as a lower bound ending at the final shared observation. One detail is equal peaks: choosing the first maximum on a plateau would include days before the decline began.

**Senior Data Engineer:** Then use the most recent equal peak preceding the worst trough. Write a regression case with 20 observations at 100, 20 at 80, then 30 at 120. The relevant peak is the twentieth observation, not the first.

**AI Coding Assistant:** The implementation and its regression test express that rule:

```python
trough = dd.idxmin()
peak = shared.loc[:trough, code].iloc[::-1].idxmax()
recovery = shared.loc[trough:, code]
recovered = recovery[recovery >= shared.loc[peak, code]]
recovery_date = recovered.index[0] if len(recovered) else pd.NaT
```

`test_duration_starts_at_last_equal_peak` asserts the twentieth observation as the peak and computes duration to the forty-first. Drawdowns remain relative to the chosen window. The function selects the first occurrence of an equally worst trough and describes that episode; it does not enumerate every episode or find the longest underwater spell.

**Senior Data Engineer:** Now challenge the AMFI comparison. If AMFI reports Friday and history stops Thursday, comparing the two latest NAVs would create a false mismatch.

**AI Coding Assistant:** Reconciliation joins on exact scheme code and date. It uses four statuses:

- `official_feed_unavailable`: no usable official record for that scheme.
- `official_date_missing_in_history`: an official record exists, but its date is absent from the history.
- `matched`: same-date values agree within tolerance.
- `value_mismatch`: same-date values differ beyond tolerance.

The tolerance is `max(0.0001, official NAV * 0.000001)`. The AMFI parser discovers fields by header rather than fixed column positions.

**Senior Data Engineer:** What does the committed sample actually show? Don't use a clean hypothetical result to describe it.

**AI Coding Assistant:** Transforming the checked-in sample produces 17,808 NAV observations and 11 findings: five peer-date-gap findings and six reconciliation findings. All six official dates are 9 October 2026 and absent from the corresponding historical data in that snapshot. The status is `official_date_missing_in_history`, not `matched`.

That is consistent with source lag in this sample, but the general status can also represent a missing historical date. It does not, by itself, establish the cause. The current UI's “lag” wording is stronger than that general guarantee.

**Senior Data Engineer:** Good distinction. Leave the review explicit about it. A future change should separate “official feed ahead” from other date gaps. Does AMFI conflict detection have the same strength as historical NAV conflict detection?

**AI Coding Assistant:** No. The parser keeps one dictionary entry per scheme; a later usable row overwrites an earlier one. It does not explicitly reject conflicting official rows. Adding that check is future work. Likewise, finding “direct” and “growth” in a scheme name is a practical guard, not full validation of its legal plan identity or benchmark mandate.

**Senior Data Engineer:** Show how the final dataset is protected. I don't want one table updated while another still belongs to an old extraction.

**AI Coding Assistant:** `publish()` writes all analytical tables to a temporary database in the destination directory. It creates unique indexes on scheme/date and scheme code, checks for NAV rows without a fund, writes run metadata, and runs SQLite's integrity check before replacement:

```python
connection.execute('CREATE UNIQUE INDEX nav_key ON nav(scheme_code, date)')
connection.execute('CREATE UNIQUE INDEX fund_key ON funds(scheme_code)')
```

After the database connection context exits, publication uses:

```python
os.replace(temporary, destination)
```

A `finally` block removes a remaining temporary file. The orphan check is an explicit query; there are no declared foreign-key constraints. The CLI logs a failed run and returns exit code 1 on an exception.

**Senior Data Engineer:** Atomic replacement is useful, but it isn't concurrent-writer arbitration or a power-loss durability guarantee. Limit the release to one ETL writer. Also, the SQLite context manager handles transaction completion, not necessarily explicit connection closure; cross-platform replacement behavior deserves a closer test before declaring it portable in every environment.

**AI Coding Assistant:** Agreed. The existing test proves that a duplicate-key publication failure leaves the prior database bytes unchanged and removes the temporary file in the tested environment. It doesn't test process termination, power failure, competing writers, or Windows file-handle behavior.

**Senior Data Engineer:** For the dashboard, show extraction freshness separately from the latest observation date. An old replay can be useful, provided the app doesn't present it as live. Explain empty selections rather than throwing an exception.

**AI Coding Assistant:** The app displays the extraction timestamp in IST, live/replay mode, actual comparison dates, and shared-date coverage. It warns when the extract is older than 48 hours or the comparison ends more than seven calendar days ago. Missing local data displays build instructions. Empty selection and incomplete date selection display prompts, and insufficient shared history displays a warning.

The Data trust view includes all watchlist findings, not only selected funds, plus reconciliation, quarantine, lineage, and quality CSV export. One limitation is that the app stops before rendering its tabs when the selection is empty or invalid, so Data trust is not independently reachable in those states.

**Senior Data Engineer:** Let's define tests concretely. For the mathematical layer, I want expected answers rather than a test that merely repeats the implementation:

1. A 100 → 80 → 120 path, padded to sufficient observations: +20% period return, −20% maximum drawdown, zero current drawdown, and recovered status.
2. A 100 → 75 path with no recovery: −25% maximum drawdown, ongoing status, and no recovery date.
3. Two funds with three missing dates in one: exactly those three dates excluded, with both indexed series beginning at 100.
4. Fifty-nine shared dates: reject comparison.
5. A long enough series: CAGR uses actual elapsed calendar days.
6. A long observation gap: exclude the bridging return from volatility inputs.
7. A strictly increasing series: zero drawdown and zero worst-episode duration.
8. The repeated-peak case we discussed: choose the last equal peak.

**AI Coding Assistant:** Those eight cases correspond to the tests in `tests/test_analytics.py`. For example, the known-path test asserts:

```python
assert metric.period_return == pytest.approx(.2)
assert metric.max_drawdown == pytest.approx(-.2)
assert metric.current_drawdown == 0
assert metric.recovery_status == 'Recovered'
assert pd.isna(metric.cagr)
```

The short path deliberately also checks that CAGR is withheld. The long-gap test verifies one excluded interval and the resulting return count, not a production holiday calendar.

**Senior Data Engineer:** For the pipeline, use the committed raw fixture so CI or a reviewer doesn't depend on live services. Require tests for invalid NAV and future-date quarantine, conflicting versus exact duplicates, wrong scheme identity, wrong plan, a missing required fund, and an unavailable optional AMFI feed.

Also test old and new AMFI column layouts, all three comparable-record outcomes, checksum tampering, previous-database preservation, and replay consistency. State exactly what the replay test establishes.

**AI Coding Assistant:** `tests/test_pipeline.py` contains those cases. The AMFI parser test is parameterized over two layouts and asserts match, value mismatch, and missing-history-date statuses. The preservation test records the prior database bytes, introduces a duplicate NAV key, attempts publication, then asserts unchanged bytes and no leftover `build-*` file.

Replay is run twice into a temporary database, and the resulting `nav` DataFrames are compared. It also verifies replay mode. It does not assert byte-for-byte database identity or equality of every table; build timestamps intentionally change.

**Senior Data Engineer:** For extraction, simulate a timeout and verify that other successful responses remain replayable and the error is recorded. Separately inspect the retry configuration. Don't claim that a configuration assertion exercises actual 429 backoff timing.

For Streamlit, test the default six-fund view, changing the peer filter to Nifty 50, and clearing fund selection. Each should complete without an app exception; the peer filter should leave three funds.

**AI Coding Assistant:** Those correspond to `tests/test_extract.py` and `tests/test_app.py`. The app test builds a temporary database from the sample, patches the configured database path, and uses Streamlit's `AppTest`. It verifies five tabs, six default funds, three Nifty 50 funds, and a helpful empty-selection message.

It is an application interaction test, not a browser screenshot comparison. The suite does not currently verify CSV download contents, every date-widget state, or all warning banners.

**Senior Data Engineer:** Run the existing suite and report the actual result. Then tell me which reliability branches still lack direct tests. Twenty-five passing tests would not mean twenty-five exhaustive guarantees.

**AI Coding Assistant:** During preparation of this simulation, the existing suite was run with:

```bash
PYTHONPYCACHEPREFIX=/tmp/fund-lens-pycache .venv/bin/python -m pytest -q
```

The observed result was:

```text
25 passed, 1 warning in 7.23s
```

The warning concerns urllib3 v2 and the local Apple Python 3.9 LibreSSL build. It was not suppressed. This was an offline test run; it did not demonstrate current upstream availability or an SLA.

Direct coverage gaps include the exact 1% quarantine boundary, every invalid-number variant, malformed JSON and wrong status cases, stale-data warning boundaries, correlation minimums and constant series, AMFI duplicate conflicts, and interruption/concurrency behavior. Some corresponding checks exist in the code; that does not make them tested branches.

**Senior Data Engineer:** Before final acceptance, review scope honestly. Does the implementation support a scalable ingestion platform, holdings-overlap analysis, or predictions?

**AI Coding Assistant:** No. It supports a local six-fund research workflow with retained source snapshots, validation, same-date reconciliation, atomic publication, and interactive retrospective analytics. It does not have distributed ingestion, holdings data, index total-return benchmarks, forecasting, automated alerts, a scheduler, or an incremental revision strategy.

The README documents the standard setup, live and replay commands, table grains, formulas, quality policy, and limitations. The repository's actual conversation-transcript directory remains a separate deliverable; this simulation does not fulfill that requirement.

**Senior Data Engineer:** Then I accept the bounded local implementation against the core review criteria: explicit source contracts, reproducible raw input, comparable dates, visible source uncertainty, protected publication, and the demonstrated calculation and interaction tests. I am not approving a production-readiness claim or signing off untested branches as covered.

My follow-up priorities are capped `Retry-After` handling, independent access to the trust view, better AMFI date-gap and duplicate classification, explicit database-handle lifecycle testing across platforms, and the missing boundary tests. After that, consider a real trading calendar, historical reconciliation, and quota-aware incremental ingestion. Add benchmark-based metrics only when the benchmark source exists.

**AI Coding Assistant:** That accurately describes the inspected repository and its next steps. The proposed enhancements remain review findings rather than claims of completed implementation. The passing suite provides evidence for the cases it exercises; the visible limitations define the boundary of that evidence.

---
