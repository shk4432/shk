"""Writes every trade of the per-timeframe backtest to results/trades_per_timeframe.csv.gz
(three signal timings x swing points on highs/lows or closes x divergence with Mega RSI or with RSI and Mega RSI,
BTCUSDT, EURUSD, XAUUSD), with the EMA 200 and AVWAP values and filter results."""
import pickle, csv, gzip, os, datetime as dt
from stats_timeframes import SYMS, passes
HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = [('early2', 'early (divergence candle)'), ('conf1', 'confirmed, 1 candle'), ('conf2', 'confirmed, 2 candles')]
f = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime('%Y-%m-%d %H:%M')
r6 = lambda v: '' if v is None else round(v, 6)
yn = lambda b: 'yes' if b else 'no'

if __name__ == '__main__':
    n = 0
    with gzip.open(f'{HERE}/results/trades_per_timeframe.csv.gz', 'wt', newline='', compresslevel=9) as fh:
        w = csv.writer(fh)
        w.writerow(['signal_timing', 'swing_points', 'divergence_with', 'symbol', 'timeframe', 'side', 'entry_time_utc', 'entry', 'stop', 'risk_pct',
                    'ema200', 'ema_ok', 'avwap_high', 'avwap_low', 'avwap_ok',
                    'result_1R', 'exit_1R_utc', 'result_2R', 'exit_2R_utc', 'result_3R', 'exit_3R_utc', 'cost_R_1R', 'skipped'])
        for run, label in RUNS:
            for sw, swing in (('', 'high/low'), ('c', 'close')):
                for o, osc in (('', 'Mega RSI'), ('b', 'RSI + Mega RSI')):
                    for sym in SYMS:
                        for t in pickle.load(open(f'{HERE}/data/trades_tf_{run}{sw}{o}_{sym}.pkl', 'rb'))['trades']:
                            o_, ex = t.get('out') or {}, t.get('exit_t') or {}
                            res = lambda k: '' if k not in o_ else f'{o_[k][0]} {o_[k][1]:+.2f}R'
                            w.writerow([label, swing, osc, sym, t['tf'], 'buy' if t['side'] == 'bu' else 'sell', f(t['t']), t['entry'], t['stop'],
                                        '' if not t.get('riskPct') else round(t['riskPct'], 4),
                                        r6(t.get('ema')), yn(passes(t, 'ema')), r6(t.get('avwap_hi')), r6(t.get('avwap_lo')), yn(passes(t, 'avwap')),
                                        res(1), f(ex[1]) if 1 in ex else '', res(2), f(ex[2]) if 2 in ex else '', res(3), f(ex[3]) if 3 in ex else '',
                                        '' if not t.get('cost') else round(t['cost'][1], 3), 'yes' if t.get('invalid') else ''])
                            n += 1
    print('rows', n)
