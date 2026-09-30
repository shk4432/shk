"""Compares the signal timings: data/trades_tf_{early2,conf1,conf2}_*.pkl -> results/timing_comparison.csv.

Needs backtest_timeframes.py to have been run for each symbol and timing:
  python3 backtest_timeframes.py BTCUSDT early     # early2: on the divergence candle
  python3 backtest_timeframes.py BTCUSDT conf 1    # conf1 : after 1 confirmation candle
  python3 backtest_timeframes.py BTCUSDT conf      # conf2 : after 2 confirmation candles
"""
import pickle, csv, os, statistics as st
from stats_timeframes import SYMS, passes
HERE = os.path.dirname(os.path.abspath(__file__))
MID = ['2H', '3H', '4H', '6H', '8H', '10H', '12H']
RUNS = [('early2', 'early (divergence candle)'), ('conf1', 'confirmed, 1 candle'), ('conf2', 'confirmed, 2 candles')]


def build():
    rows = []
    for run, label in RUNS:
        data = {s: pickle.load(open(f'{HERE}/data/trades_tf_{run}_{s}.pkl', 'rb'))['trades'] for s in SYMS}
        for sym in SYMS + ['ALL']:
            trs = data[sym] if sym != 'ALL' else [t for s in SYMS for t in data[s]]
            for band, tfs in (('2H-12H', MID), ('all timeframes', None)):
                for f in ('none', 'ema'):
                    pm = [t for t in trs if (tfs is None or t['tf'] in tfs) and passes(t, f) and not t.get('invalid')]
                    for k in (1, 2, 3):
                        g = [t['out'][k][1] for t in pm if t['out'][k][0] != 'open']
                        nt = [t['out'][k][1] - t['cost'][k] for t in pm if t['out'][k][0] != 'open']
                        wins = sum(1 for t in pm if t['out'][k][0] == 'win')
                        closed = len(g)
                        rows.append([sym, label, band, 'EMA 200' if f == 'ema' else 'none', f'{k}R', len(pm), wins, closed - wins,
                                     round(wins / closed * 100, 1) if closed else '', round(st.mean(g), 3) if g else '',
                                     round(st.mean(nt), 3) if nt else '', round(1.96 * st.pstdev(nt) / len(nt) ** 0.5, 3) if len(nt) > 1 else ''])
    return rows


if __name__ == '__main__':
    rows = build()
    with open(f'{HERE}/results/timing_comparison.csv', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['symbol', 'signal_timing', 'timeframes', 'trend_filter', 'target', 'trades', 'wins', 'losses', 'win_pct', 'avg_R_gross', 'avg_R_net', 'ci95_net'])
        w.writerows(rows)
    print('rows', len(rows))
