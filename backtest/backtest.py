"""Backtest of the Mega RSI MTF divergence signals on Binance data.

Signal generation reuses ref.mtf / ref.scan (verified bar-for-bar against the Pine script in PineTS).
Entry modes:
  A  = close of the 5m candle on which the signal appears (alert moment)
  B  = close of the candle of the group's smallest timeframe (chart = that timeframe)
Stop modes:
  HTF = low (long) / high (short) of the pivot candle of divergence point 2 on the group's largest timeframe
  LTF = same, on the group's smallest timeframe
Targets 1R/2R/3R share the stop; time limit = 20 candles of the group's largest timeframe.
A candle that touches both stop and target counts as a loss. Fees: 0.1% round trip (0.05% per side).
"""
import json, sys, os, math, pickle, datetime as dt
import engine as ref

HERE = os.path.dirname(os.path.abspath(__file__))
DAY, MIN = ref.DAY, ref.MIN
T0 = int(dt.datetime(2025, 9, 30, tzinfo=dt.timezone.utc).timestamp() * 1000)   # signals from
T1 = int(dt.datetime(2026, 9, 29, 23, 55, tzinfo=dt.timezone.utc).timestamp() * 1000)  # last 5m candle
FEE_SIDE = 0.0005
TIME_LIMIT = 20
LADDER = ref.LADDER
TFSEC = {tf: ref.tf_seconds(tf) for tf, _ in LADDER}
TFSEC['1M'] = 2628003   # TradingView's timeframe.in_seconds("1M")

_orig_tf_seconds = ref.tf_seconds
def tf_seconds(tf):
    return 2628003 if tf in ('1M', 'M') else _orig_tf_seconds(tf)
ref.tf_seconds = tf_seconds


def load(sym):
    k5 = json.load(open(f'{HERE}/data/{sym}-5m.json'))
    kd = json.load(open(f'{HERE}/data/{sym}-1d.json'))
    return k5, kd


def make_candles(k5, kd):
    cache = {}
    def candles(tf, t_from=None, t_to=None):
        key = tf
        if key not in cache:
            src = kd if tf[-1] in 'DWM' else k5
            out = []
            for (t, o, h, l, c) in src:
                bo, bc = ref.bucket(t, tf)
                if out and out[-1]['ot'] == bo:
                    x = out[-1]; x['h'] = max(x['h'], h); x['l'] = min(x['l'], l); x['c'] = c
                else:
                    out.append(dict(ot=bo, ct=bc, o=o, h=h, l=l, c=c))
            cache[key] = out
        out = cache[key]
        if t_from is not None:
            out = [x for x in out if x['ot'] >= t_from]
        if t_to is not None:
            out = [x for x in out if x['ot'] <= t_to]
        return out
    return candles


def signals(sym, mode):
    """Returns list of dicts: time (entry candle close), entry, side, group, stops, time limit."""
    k5, kd = load(sym)
    ref.candles = make_candles(k5, kd)
    p = dict(ref.P)
    sigs = []
    names = [nm for _, nm in LADDER]
    tf_of = {nm: tf for tf, nm in LADDER}
    need = p['needTF']
    groups = [names[j:j + need] for j in range(len(names) - need + 1)]
    runs = [('5', None)] if mode == 'A' else [(tf_of[g[0]], g) for g in groups]
    for chart_tf, grp in runs:
        chart, per_tf, fires = ref.mtf(chart_tf, T0, T1, p=p, buf_days=4000, enabled=set(grp) if grp else None)
        idx = {c['ot']: i for i, c in enumerate(chart)}
        pos = {nm: k for k, (_, nm, _, _) in enumerate(per_tf)}
        for (ot, side, gname) in fires:
            ci = idx[ot]
            g = gname.split(' · ')
            st = [per_tf[pos[nm]][3][ci][side] for nm in g]
            secs = [TFSEC[tf_of[nm]] for nm in g]
            hi = max(range(need), key=lambda k: secs[k]); lo = min(range(need), key=lambda k: secs[k])
            sigs.append(dict(sym=sym, mode=mode, group=gname, side=side, t=chart[ci]['ct'], entry=chart[ci]['c'],
                             stopHTF=st[hi]['p2'], stopLTF=st[lo]['p2'], limit=chart[ci]['ct'] + TIME_LIMIT * secs[hi] * 1000,
                             osc=st[hi]['osc'], t2=st[hi]['t2']))
    return sigs


def simulate(sig, bars5, times5, stop_key):
    """Walks 5m candles after entry. Returns per-target outcome dict."""
    import bisect
    long = sig['side'] == 'bu'
    E, S = sig['entry'], sig[stop_key]
    R = (E - S) if long else (S - E)
    res = dict(R=R, riskPct=R / E * 100 if R > 0 else None)
    if R <= 0:
        res['invalid'] = True
        return res
    i = bisect.bisect_left(times5, sig['t'])       # first 5m candle opening at/after the entry candle close
    mfe = 0.0
    outcome = {k: None for k in (1, 2, 3)}          # 'win' | 'loss' | ('exp', R) | ('open', R)
    last_close = E
    stopped = False
    while i < len(bars5):
        t, o, h, l, c = bars5[i]
        if t >= sig['limit']:
            break
        hit_stop = (l <= S) if long else (h >= S)
        if hit_stop:
            for k in outcome:
                if outcome[k] is None:
                    outcome[k] = 'loss'
            stopped = True
            break
        fav = ((h - E) if long else (E - l)) / R
        if fav > mfe:
            mfe = fav
            for k in outcome:
                if outcome[k] is None and mfe >= k:
                    outcome[k] = 'win'
        last_close = c
        i += 1
        if all(v is not None for v in outcome.values()):
            break
    end_r = ((last_close - E) if long else (E - last_close)) / R
    ended = i >= len(bars5) and not stopped
    for k in outcome:
        if outcome[k] is None:
            outcome[k] = ('open', end_r) if ended else ('exp', end_r)
    res['out'] = outcome
    res['mfe'] = mfe
    return res


def run(sym):
    k5, _ = load(sym)
    times5 = [b[0] for b in k5]
    trades = []
    for mode in ('A', 'B'):
        for s in signals(sym, mode):
            if not (T0 <= s['t'] <= T1 + 5 * MIN):
                continue
            for stop_key in ('stopHTF', 'stopLTF'):
                r = simulate(s, k5, times5, stop_key)
                trades.append(dict(s, stop=stop_key[4:], **r))
    pickle.dump(trades, open(f'{HERE}/data/trades_{sym}.pkl', 'wb'))
    print(sym, 'trades', len(trades), flush=True)


if __name__ == '__main__':
    run(sys.argv[1])
