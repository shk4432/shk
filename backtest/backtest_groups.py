"""Backtest of the chosen setup plus the 3-timeframe rule.

Setup (as in backtest_timeframes.py ... conf 2 close both): swing points on closes, signal after the second swing
is confirmed with 2 candles, divergence with RSI and Mega RSI together, timeframes 2H to 12H.

3-timeframe rule (the original rule of the indicator, engine.mtf):
  three consecutive timeframes of the ladder 2H 3H 4H 6H 8H 10H 12H have an active divergence of the same direction
  at the same moment, and their second swing points are the same swing: each lies within one candle of the largest
  of the three timeframes from the largest timeframe's second swing point. The signal comes when a group becomes
  true; the same group gives one signal per swing.
Trade: entry at the close of that 5m candle; stop = low (long) / high (short) of the candle of the second swing point
of the largest timeframe of the group (the smallest timeframe's stop is simulated too); targets 1R/2R/3R; no time limit.
Filters are applied in group_trades(): EMA 200 of all three timeframes (or none). One trade per swing: a signal is not
a new trade when the candle of one of its second swing points overlaps in time with the candle of a second swing point
of a trade already taken in the same direction (the same swing seen by another group, e.g. 3H-4H-6H and 8H-10H-12H).

  python3 backtest_groups.py BTCUSDT [years]   -> data/trades_grp_conf2cb_{years}y_BTCUSDT.pkl
"""
import sys, os, pickle, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
import backtest as bt2
from backtest import ref, COST_SIDE, MIN, TF_OF, tf_seconds
from backtest_timeframes import load_window, simulate

MID = ['2H', '3H', '4H', '6H', '8H', '10H', '12H']
P = dict(ref.P)
P.update(early=False, pivR=2, useClose=True, mode='BOTH', needTF=3, syncOn=True, syncTol=1, groups='up')


def group_signals(candles, t0, t1):
    ref.candles = candles
    chart, per_tf, fires = ref.mtf('5', t0, t1, p=P, buf_days=4000, enabled=set(MID))
    assert [nm for _, nm, _, _ in per_tf] == MID
    idx = {c['ot']: i for i, c in enumerate(chart)}
    pos = {nm: k for k, (_, nm, _, _) in enumerate(per_tf)}
    sigs = []
    for (ot, side, gname) in fires:
        ci = idx[ot]
        if ci == 0:
            continue            # already true before the window: signalled earlier
        g = gname.split(' · ')
        st = [per_tf[pos[nm]][3][ci][side] for nm in g]
        cb = chart[ci]
        sigs.append(dict(group=gname, tfs=g, side=side, ot=cb['ot'], t=cb['ct'], entry=cb['c'],
                         t2s=[s['t2'] for s in st], p2s=[s['p2'] for s in st], sls=[s['sl'] for s in st],
                         osc=[s['osc'] for s in st]))
    return sigs


def run(sym, years=5):
    market, candles, base5, t0, t1 = load_window(sym, years)
    times5 = [b[0] for b in base5]
    ix = bt2.TFIndex(candles)
    trades = []
    for s in group_signals(candles, t0, t1):
        if not (t0 <= s['t'] <= t1 + 5 * MIN):
            continue
        # every timeframe of the group is above the 5m chart: EMA of its last closed candle
        s['emas'] = [ix.ema_at(TF_OF[tf], s['ot']) for tf in s['tfs']]
        s['sym'], s['market'] = sym, market
        for name, stop in (('large', s['sls'][-1]), ('small', s['sls'][0])):
            r = simulate(dict(s, stop=stop), base5, times5, COST_SIDE[market])
            s[name] = dict(stop=stop, **r)
        trades.append(s)
    pickle.dump(dict(trades=trades, t0=t0, t1=t1, last=base5[-1][0]),
                open(f'{HERE}/data/trades_grp_conf2cb_{years}y_{sym}.pkl', 'wb'))
    print(sym, 'group signals', len(trades), dt.datetime.utcfromtimestamp(t0 / 1000).date(), '->',
          dt.datetime.utcfromtimestamp(t1 / 1000).date(), flush=True)


def ema_ok(t):
    if any(e is None for e in t['emas']):
        return False
    return all(t['entry'] > e for e in t['emas']) if t['side'] == 'bu' else all(t['entry'] < e for e in t['emas'])


def group_trades(signals, f='ema', stop='large'):
    """Trades actually taken with filter f ('ema' or 'none') and stop ('large' or 'small'): flat dicts like the
    per-timeframe trades (out, cost, exit_t, riskPct, ...), one per swing."""
    used, out = {'bu': [], 'be': []}, []
    for s in sorted(signals, key=lambda x: (x['t'], MID.index(x['tfs'][0]))):
        r = s[stop]
        if r.get('invalid') or (f == 'ema' and not ema_ok(s)):
            continue                                  # no signal: the price is beyond the stop or on the wrong side of an EMA
        spans = [(t2, t2 + tf_seconds(TF_OF[tf]) * 1000) for tf, t2 in zip(s['tfs'], s['t2s'])]
        if any(a < d and c < b for a, b in spans for c, d in used[s['side']]):
            continue                                  # same swing as a trade already taken
        used[s['side']] += spans
        out.append(dict(s, **r, tf=s['group']))
    return out


if __name__ == '__main__':
    run(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 5)
