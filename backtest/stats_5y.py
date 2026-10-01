"""Five-year statistics of one indicator setup: data/trades_tf_{RUN}_5y_*.pkl -> results/combo_5y.csv.

Default RUN = conf2cb: signal after 2 confirmation candles, swing points on closes, divergence with RSI and
Mega RSI together. The EMA 200 filter of the divergence's own timeframe is applied here (and 'none' for reference).
Rows: symbol (and all three), test year (1 = the oldest), timeframe band, filter, target.
The last year is the one the setup was picked on; years 1-4 were not used to pick it.
"""
import sys, os, csv, pickle, statistics as st, datetime as dt
from stats_timeframes import SYMS, TFS, passes, agg
HERE = os.path.dirname(os.path.abspath(__file__))
RUN = sys.argv[1] if len(sys.argv) > 1 else 'conf2cb'
MID = ['2H', '3H', '4H', '6H', '8H', '10H', '12H']
BANDS = (('2H-12H', MID), ('all timeframes', TFS))


def load():
    data = {s: pickle.load(open(f'{HERE}/data/trades_tf_{RUN}_5y_{s}.pkl', 'rb')) for s in SYMS}
    for s, d in data.items():
        # test year of every trade: year 1 starts at t0, each year ends on the same calendar day
        t0 = dt.datetime.fromtimestamp(d['t0'] / 1000, dt.timezone.utc)
        edges = [int(t0.replace(year=t0.year + y).timestamp() * 1000) for y in range(1, 6)]
        for t in d['trades']:
            t['year'] = 1 + sum(1 for e in edges if t['t'] >= e)
    return data


def curve(trs, k, net=True):
    """Closed trades in the order they closed (realised result): cumulative R, max drawdown, longest losing streak."""
    seq = sorted((t for t in trs if not t.get('invalid') and t['out'][k][0] != 'open'), key=lambda t: (t['exit_t'][k], t['t']))
    cum = peak = dd = 0.0
    streak = longest = 0
    for t in seq:
        r = t['out'][k][1] - (t['cost'][k] if net else 0)
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    return round(cum, 2), round(dd, 2), longest


def rows(data):
    out = []
    for sym in SYMS + ['ALL']:
        pool = data[sym]['trades'] if sym != 'ALL' else [t for s in SYMS for t in data[s]['trades']]
        for year in ('1-5', '1-4', 1, 2, 3, 4, 5):
            py = [t for t in pool if (year == '1-5' or (year == '1-4' and t['year'] <= 4) or t['year'] == year)]
            for band, tfs in BANDS:
                for f in ('ema', 'none'):
                    pm = [t for t in py if t['tf'] in tfs and passes(t, f)]
                    for k in (1, 2, 3):
                        a, g = agg(pm, k, 1), agg(pm, k, 0)
                        out.append([sym, year, band, 'EMA 200' if f == 'ema' else 'none', f'{k}R', a[0], a[1], a[2], a[3], a[4], g[5], a[5], a[6]]
                                   + list(curve(pm, k)))
    return out


if __name__ == '__main__':
    data = load()
    with open(f'{HERE}/results/combo_5y.csv', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['symbol', 'test_year', 'timeframes', 'filter', 'target', 'trades', 'wins', 'losses', 'open', 'win_pct',
                    'avg_R_gross', 'avg_R_net', 'ci95_net', 'total_R_net', 'max_drawdown_R', 'longest_losing_streak'])
        w.writerows(rows(data))
    for s in SYMS:
        d = data[s]
        print(s, len(d['trades']), dt.datetime.utcfromtimestamp(d['t0'] / 1000), '->', dt.datetime.utcfromtimestamp(d['t1'] / 1000))
