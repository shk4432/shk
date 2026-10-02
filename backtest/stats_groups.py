"""Five-year statistics of the 3-timeframe rule: data/trades_grp_conf2cb_5y[_low]_*.pkl -> results/groups_5y[_low].csv
and results/groups_5y[_low]_trades.csv.   python3 stats_groups.py [mid|low]

Rows: symbol (and all three), test year (1 = the oldest; 5 = the year the setup was picked on), filter
(EMA 200 of all three timeframes, or none), stop (largest or smallest timeframe of the group), target.
The per-timeframe baseline of the same setup is in results/combo_5y.csv.
"""
import os, sys, csv, pickle, datetime as dt
from stats_timeframes import SYMS, agg
from stats_5y import curve
from backtest_groups import group_trades, suffix
BAND = sys.argv[1] if len(sys.argv) > 1 else 'mid'
HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    out = {}
    for s in SYMS:
        d = pickle.load(open(f'{HERE}/data/trades_grp_conf2cb_5y{suffix(BAND)}_{s}.pkl', 'rb'))
        t0 = dt.datetime.fromtimestamp(d['t0'] / 1000, dt.timezone.utc)
        edges = [int(t0.replace(year=t0.year + y).timestamp() * 1000) for y in range(1, 6)]
        for t in d['trades']:
            t['year'] = 1 + sum(1 for e in edges if t['t'] >= e)
        out[s] = d
    return out


def taken(data, f, stop):
    return {s: group_trades(data[s]['trades'], f, stop) for s in SYMS}


def rows(data):
    out = []
    for f in ('ema', 'none'):
        for stop in ('large', 'small'):
            tk = taken(data, f, stop)
            groups = sorted({t['group'] for s in SYMS for t in tk[s]}, key=lambda g: [t['tfs'] for s in SYMS for t in tk[s] if t['group'] == g][0][0].rjust(4))
            for sym in SYMS + ['ALL']:
                pool = tk[sym] if sym != 'ALL' else [t for s in SYMS for t in tk[s]]
                for grp in ['all'] + groups:
                    pg = pool if grp == 'all' else [t for t in pool if t['group'] == grp]
                    for year in ('1-5', '1-4', 1, 2, 3, 4, 5):
                        py = [t for t in pg if year == '1-5' or (year == '1-4' and t['year'] <= 4) or t['year'] == year]
                        for k in (1, 2, 3):
                            a, g = agg(py, k, 1), agg(py, k, 0)
                            out.append([sym, grp, year, 'EMA 200' if f == 'ema' else 'none', stop, f'{k}R', a[0], a[1], a[2], a[3], a[4],
                                        g[5], a[5], a[6]] + list(curve(py, k)))
    return out


def trade_list(data, f='ema', stop='large'):
    """Every trade taken with the main settings, for checking on a chart."""
    fmt = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime('%Y-%m-%d %H:%M')
    rows = []
    for s in SYMS:
        for t in group_trades(data[s]['trades'], f, stop):
            res = lambda k: f"{t['out'][k][0]} {t['out'][k][1] - t['cost'][k]:+.2f}R"
            rows.append([s, t['year'], fmt(t['t']), t['group'], 'buy' if t['side'] == 'bu' else 'sell', t['entry'], t['stop'],
                         round(t['riskPct'], 3), ' · '.join(fmt(x) for x in t['t2s']), res(1), res(2), res(3),
                         fmt(t['exit_t'][3]) if 3 in t['exit_t'] else ''])
    return sorted(rows, key=lambda r: r[2])


if __name__ == '__main__':
    data = load()
    with open(f'{HERE}/results/groups_5y{suffix(BAND)}_trades.csv', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['symbol', 'test_year', 'entry_time_utc', 'group', 'side', 'entry', 'stop', 'risk_pct',
                    'second_swing_point_times_utc', 'result_1R_net', 'result_2R_net', 'result_3R_net', 'exit_3R_utc'])
        w.writerows(trade_list(data))
    with open(f'{HERE}/results/groups_5y{suffix(BAND)}.csv', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['symbol', 'group', 'test_year', 'filter', 'stop', 'target', 'trades', 'wins', 'losses', 'open', 'win_pct',
                    'avg_R_gross', 'avg_R_net', 'ci95_net', 'total_R_net', 'max_drawdown_R', 'longest_losing_streak'])
        w.writerows(rows(data))
    for s in SYMS:
        print(s, 'group signals', len(data[s]['trades']), '| taken with EMA, large stop', len(group_trades(data[s]['trades'])))
