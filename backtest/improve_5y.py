"""Four ideas to improve the chosen setup, each tested on its own on the same five years.

Setup (unchanged): signal after 2 confirmation candles, swing points on closes, divergence with RSI and Mega RSI
together, timeframes 2H-12H, EMA 200 of the divergence's own timeframe, entry at the close of the 5m candle
on which the signal is visible, stop = low/high of the point-2 candle, no time limit.

  1 manage : half closed at 1R and the stop moved to the entry, the rest to 2R / 3R ('half1');
             or the stop moved to the entry at +0.5R, no partial close ('be05')
  2 buffer : stop 0.25 / 0.5 ATR(14) beyond the low/high of the point-2 candle (ATR of the divergence's
             timeframe, last closed candle at the signal) - targets are measured from the wider stop
  3 quality: RSI(14) at point 2 (buy below 40 / 35, sell above 60 / 65), RSI difference between the two points
             (at least 5), distance between the two points (at least 10 candles of that timeframe)
  4 trend  : daily EMA 200 on the same side as well, or the own EMA 200 sloping the trade's way
             (higher / lower than 10 candles before)

Reads the signals of data/trades_tf_conf2cb_5y_{sym}.pkl and re-simulates them on the same 5m candles.
The plain re-simulation must reproduce the stored results exactly (checked here).
-> data/improve_5y_{sym}.pkl

python3 improve_5y.py BTCUSDT
"""
import sys, os, bisect, pickle
HERE = os.path.dirname(os.path.abspath(__file__))
import backtest as bt2
from backtest import ref, COST_SIDE, TF_OF
from backtest_timeframes import load_window
from stats_timeframes import passes

MID = ['2H', '3H', '4H', '6H', '8H', '10H', '12H']
P = dict(ref.P); P.update(early=False, pivR=2, useClose=True, mode='BOTH')
TARGETS = (1, 2, 3)
BUFFERS = (0.25, 0.5)
SLOPE_BARS = 10


def walk(E, S, long, t, bars5, times5, cost_side, T, be_at=None, part=0.0):
    """One trade on 5m candles: target T (R), optional stop to the entry once +be_at R is reached, with `part`
    of the position closed there. Same rules as backtest_timeframes.simulate: the stop is checked before the
    target in every candle (a candle touching both = stop), a gap through the stop fills at the open.
    The stop moves to the entry from the next candle on; if the candle that reached be_at also touched the
    entry, the rest is closed at the entry (the order inside a candle is unknown, so the worse case).
    Returns dict(kind, r, cost, exit_t) with kind 'win' (r > 0), 'be' (r == 0), 'loss' (r < 0) or 'open'."""
    R = (E - S) if long else (S - E)
    i = bisect.bisect_left(times5, t)
    stop, stop_r = S, -1.0
    rem, got, legs, armed, last = 1.0, 0.0, [], be_at is None, E

    def done(x, when):
        nonlocal got
        legs.append((rem, x)); got += rem * x
        cost = sum(f * cost_side * (E + (E + r * R if long else E - r * R)) / R for f, r in legs)
        return dict(kind='win' if got > 1e-12 else 'loss' if got < -1e-12 else 'be', r=got, cost=cost, exit_t=when)

    while i < len(bars5):
        tt, o, h, l, c = bars5[i]
        if (l <= stop) if long else (h >= stop):
            gap = (o <= stop) if long else (o >= stop)
            return done(min(stop_r, ((o - E) if long else (E - o)) / R) if gap else stop_r, tt)
        fav = ((h - E) if long else (E - l)) / R
        if not armed and fav >= be_at:
            armed = True
            if part:
                legs.append((part, be_at)); got += part * be_at; rem -= part
            if fav < T and ((l <= E) if long else (h >= E)):
                return done(0.0, tt)
            stop, stop_r = E, 0.0
        if fav >= T:
            return done(float(T), tt)
        last = c
        i += 1
    end_r = ((last - E) if long else (E - last)) / R
    return dict(kind='open', r=got + rem * end_r, cost=0.0, exit_t=None)


def atr_series(bars, n=14):
    tr = [b['h'] - b['l'] if i == 0 else max(b['h'] - b['l'], abs(b['h'] - bars[i - 1]['c']), abs(b['l'] - bars[i - 1]['c']))
          for i, b in enumerate(bars)]
    return bt2.rma(tr, n)


def points(candles):
    """(side, timeframe, time of point 2) -> RSI at both points, distance in candles, stop - from the engine's own scan."""
    out = {}
    for tf in MID:
        bars = candles(TF_OF[tf])
        rs = ref.rsi([b['c'] for b in bars], P['rsiLen'])
        at = {b['ot']: i for i, b in enumerate(bars)}
        for st in ref.scan(bars, P):
            for side in ('bu', 'be'):
                s = st[side]
                key = (side, tf, s['t2'])
                if s['on'] and key not in out:
                    b1 = at[s['t1']]
                    out[key] = dict(r1=rs[b1], r2=rs[s['b2']], dist=s['b2'] - b1, sl=s['sl'])
    return out


def run(sym):
    d = pickle.load(open(f'{HERE}/data/trades_tf_conf2cb_5y_{sym}.pkl', 'rb'))
    market, candles, base5, t0, t1 = load_window(sym, 5)
    assert (t0, t1) == (d['t0'], d['t1']), 'test window differs from the stored run'
    times5 = [b[0] for b in base5]
    cs = COST_SIDE[market]
    ix = bt2.TFIndex(candles)
    pts = points(candles)
    atr = {tf: atr_series(ix.get(TF_OF[tf])[0]) for tf in MID}
    trades = [t for t in d['trades'] if t['tf'] in MID and passes(t, 'ema')]
    checked = 0
    for t in trades:
        long = t['side'] == 'bu'
        E, S = t['entry'], t['stop']
        bars, ots, cts, ema = ix.get(TF_OF[t['tf']])
        i = bisect.bisect_right(cts, t['ot']) - 1
        assert ema[i] == t['ema']
        p = pts[(t['side'], t['tf'], t['t2'])]
        assert p['sl'] == S
        f = dict(atr=atr[t['tf']][i], ema_slope=ema[i] - ema[i - SLOPE_BARS], ema_daily=ix.ema_at('1D', t['ot']),
                 r1=p['r1'], r2=p['r2'], dist=p['dist'])
        sims = {}
        if not t.get('invalid'):
            for k in TARGETS:
                sims[('plain', k)] = walk(E, S, long, t['t'], base5, times5, cs, k)
                o = sims[('plain', k)]
                ref_kind, ref_r = t['out'][k]
                assert o['kind'] == ref_kind or (ref_kind == 'open' and o['kind'] == 'open'), (t, k, o)
                if ref_kind != 'open':
                    assert abs(o['r'] - ref_r) < 1e-9 and abs(o['cost'] - t['cost'][k]) < 1e-9 and o['exit_t'] == t['exit_t'][k], (t, k, o)
                checked += 1
                sims[('half1', k)] = walk(E, S, long, t['t'], base5, times5, cs, k, be_at=1.0, part=0.5) if k > 1 else None
                sims[('be05', k)] = walk(E, S, long, t['t'], base5, times5, cs, k, be_at=0.5)
        for b in BUFFERS:
            Sb = S - b * f['atr'] if long else S + b * f['atr']
            ok = (E > Sb) if long else (E < Sb)
            for k in TARGETS:
                sims[(f'buf{b}', k)] = walk(E, Sb, long, t['t'], base5, times5, cs, k) if ok else None
            f[f'risk_buf{b}'] = abs(E - Sb) / E * 100 if ok else None
        t['feat'], t['sims'] = f, {k: v for k, v in sims.items() if v is not None}
    pickle.dump(dict(trades=trades, t0=d['t0'], t1=d['t1']), open(f'{HERE}/data/improve_5y_{sym}.pkl', 'wb'))
    print(sym, 'trades', len(trades), 'valid', sum(1 for t in trades if not t.get('invalid')),
          'plain results reproduced', checked, flush=True)


if __name__ == '__main__':
    run(sys.argv[1])
