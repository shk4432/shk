"""Backtest of the per-timeframe signals (current indicator logic).

Every new divergence on any of the 19 timeframes is a trade: bullish = long, bearish = short.
  timing : 'early' = the candle that forms the divergence; 'conf' = after pivR confirmation candles
  entry  : close of the first 5m candle on which the divergence is visible (alert moment)
  stop   : low (long) / high (short) of that timeframe's pivot candle of divergence point 2
  targets: 1R, 2R, 3R, each on its own; no time limit - a trade ends only at target or stop
           (still open at the end of the data = 'open')
  filter : none, or EMA 200 of the divergence's own timeframe (last closed candle), as in the indicator;
           the ADX (14, 14) of that timeframe at the same moment is stored for the ADX > 20 filter
"""
import sys, os, pickle, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
import backtest as bt2
from backtest import ref, MARKET, COST_SIDE, DAY, MIN, TF_OF

NO_LIMIT = 10 ** 15


def signals(candles, t0, t1, early, pivR=2):
    ref.candles = candles
    P = dict(ref.P); P['early'] = early; P['pivR'] = pivR
    chart, per_tf, _ = ref.mtf('5', t0, t1, p=P, buf_days=4000)
    sigs = []
    for tf, nm, sec, vals in per_tf:
        fired = {'bu': 0, 'be': 0}
        for ci, cb in enumerate(chart):
            v = vals[ci]
            for side in ('bu', 'be'):
                st = v[side]
                if st['on'] and fired[side] != st['t2']:
                    fired[side] = st['t2']
                    sigs.append(dict(tf=nm, side=side, ot=cb['ot'], t=cb['ct'], entry=cb['c'], stop=st['p2'],
                                     t2=st['t2'], osc=st['osc'], limit=NO_LIMIT))
    return sigs


def simulate(sig, bars5, times5, cost_side):
    """Walks 5m candles until target or stop (no time limit). Records the exit time per target."""
    import bisect
    long = sig['side'] == 'bu'
    E, S = sig['entry'], sig['stop']
    R = (E - S) if long else (S - E)
    if R <= 0:
        return dict(R=R, invalid=True)
    i = bisect.bisect_left(times5, sig['t'])
    mfe, out, exit_t, last = 0.0, {1: None, 2: None, 3: None}, {}, E
    while i < len(bars5):
        t, o, h, l, c = bars5[i]
        if (l <= S) if long else (h >= S):
            gap = (o <= S) if long else (o >= S)
            r = min(-1.0, ((o - E) if long else (E - o)) / R) if gap else -1.0
            for k in out:
                if out[k] is None:
                    out[k] = ('loss', r); exit_t[k] = t
            break
        fav = ((h - E) if long else (E - l)) / R
        if fav > mfe:
            mfe = fav
            for k in out:
                if out[k] is None and mfe >= k:
                    out[k] = ('win', float(k)); exit_t[k] = t
        last = c
        i += 1
        if all(v is not None for v in out.values()):
            break
    end_r = ((last - E) if long else (E - last)) / R
    for k in out:
        if out[k] is None:
            out[k] = ('open', end_r)
    cost = {k: cost_side * (E + (E + v[1] * R if long else E - v[1] * R)) / R for k, v in out.items()}
    return dict(R=R, riskPct=R / E * 100, out=out, cost=cost, mfe=mfe, exit_t=exit_t)


def run(sym, timing, pivR=2):
    early = timing == 'early'
    market = MARKET[sym]
    if market == 'crypto':
        candles, base5 = bt2.load_crypto(sym)
        t0 = int(dt.datetime(2025, 9, 30, tzinfo=dt.timezone.utc).timestamp() * 1000)
        t1 = int(dt.datetime(2026, 9, 29, 23, 55, tzinfo=dt.timezone.utc).timestamp() * 1000)
    else:
        candles, base5 = bt2.load_session(sym, market, int(dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000))
        t1 = base5[-1][0]
        t0 = t1 - 365 * DAY
    base5 = [tuple(b) for b in base5]
    times5 = [b[0] for b in base5]
    ix = bt2.TFIndex(candles)
    trades = []
    for s in signals(candles, t0, t1, early, pivR):
        if not (t0 <= s['t'] <= t1 + 5 * MIN):
            continue
        # the chart's own timeframe (5m) is read from the current candle, higher ones from the last closed candle
        at = s['t'] if s['tf'] == '5m' else s['ot']
        s['ema'] = ix.ema_at(TF_OF[s['tf']], at)
        s['adx'] = ix.adx_at(TF_OF[s['tf']], at)
        r = simulate(s, base5, times5, COST_SIDE[market])
        s.update(sym=sym, market=market, **r)
        trades.append(s)
    pickle.dump(dict(trades=trades, t0=t0, t1=t1, last=base5[-1][0]), open(f'{HERE}/data/trades_tf_{timing}{pivR}_{sym}.pkl', 'wb'))
    print(sym, 'signals', len(trades), dt.datetime.utcfromtimestamp(t0 / 1000).date(), '->', dt.datetime.utcfromtimestamp(t1 / 1000).date(), flush=True)


if __name__ == '__main__':
    # python3 backtest_timeframes.py BTCUSDT early|conf [pivR]
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'early', int(sys.argv[3]) if len(sys.argv) > 3 else 2)
