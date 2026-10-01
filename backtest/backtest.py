"""Backtest of the Mega RSI MTF divergence signals.

Includes:
  * forex / gold / US index data (histdata.com 1-minute bars) with TradingView-like sessions:
      fx  : sessions start 17:00 New York (EURUSD, GBPUSD, XAUUSD)
      rth : regular hours 09:30-16:00 New York only (S&P 500, Nasdaq-100)
  * EMA 200 trend filter (long only above, short only below), measured on the group's smallest
    timeframe, its largest timeframe, or the daily chart; the value of the last closed candle is used
  * time limit = 20 candles of the group's largest timeframe, counted on real candles
  * a stop gapped through at a candle open is filled at that open
"""
import json, sys, os, bisect, pickle, datetime as dt
from zoneinfo import ZoneInfo
HERE = os.path.dirname(os.path.abspath(__file__))
import engine as ref

NY = ZoneInfo('America/New_York')
MIN, DAY = ref.MIN, ref.DAY
LADDER = ref.LADDER
NAMES = [nm for _, nm in LADDER]
TF_OF = {nm: tf for tf, nm in LADDER}
TIME_LIMIT = 20
EMA_LEN = 200
ADX_DI_LEN = 14   # ADX filter: DI length and ADX smoothing of TradingView's built-in ADX
ADX_LEN = 14
MARKET = {'BTCUSDT': 'crypto', 'ETHUSDT': 'crypto', 'SOLUSDT': 'crypto', 'ZECUSDT': 'crypto', 'HYPEUSDT': 'crypto',
          'EURUSD': 'fx', 'GBPUSD': 'fx', 'XAUUSD': 'fx', 'SPXUSD': 'rth', 'NSXUSD': 'rth'}
COST_SIDE = {'crypto': 0.0005, 'fx': 0.0001, 'rth': 0.0001}

_orig_tf_seconds = ref.tf_seconds
def tf_seconds(tf):
    return 2628003 if tf in ('1M', 'M') else _orig_tf_seconds(tf)
ref.tf_seconds = tf_seconds


# ── sessions ──────────────────────────────────────────────────────────────
_off = {}
def ny_off(t):
    h = t // 3600000
    v = _off.get(h)
    if v is None:
        v = _off[h] = int(dt.datetime.fromtimestamp(t / 1000, NY).utcoffset().total_seconds() * 1000)
    return v


def session(t, market):
    """(session start utc, session end utc, session day number) or None outside the session."""
    off = ny_off(t)
    L = t + off
    if market == 'fx':
        k = (L + 7 * 3600000) // DAY
        ss = k * DAY - 7 * 3600000 - off
        return ss, ss + DAY, k
    tod = L % DAY
    if tod < 9.5 * 3600000 or tod >= 16 * 3600000:
        return None
    k = L // DAY
    return k * DAY + int(9.5 * 3600000) - off, k * DAY + 16 * 3600000 - off, k


def weekday(k):
    return (k + 3) % 7   # 0 = Monday


# ── candle sources ────────────────────────────────────────────────────────
def load_crypto(sym):
    k5 = json.load(open(f'{HERE}/data/{sym}-5m.json'))
    kd = json.load(open(f'{HERE}/data/{sym}-1d.json'))
    cache = {}
    def candles(tf, t_from=None, t_to=None):
        if tf not in cache:
            src = kd if tf[-1] in 'DWM' else k5
            out = []
            for (t, o, h, l, c) in src:
                bo, bc = ref.bucket(t, tf)
                if out and out[-1]['ot'] == bo:
                    x = out[-1]; x['h'] = max(x['h'], h); x['l'] = min(x['l'], l); x['c'] = c
                else:
                    out.append(dict(ot=bo, ct=bc, o=o, h=h, l=l, c=c))
            cache[tf] = out
        return _clip(cache[tf], t_from, t_to)
    return candles, k5


def _clip(out, t_from, t_to):
    if t_from is not None:
        out = [x for x in out if x['ot'] >= t_from]
    if t_to is not None:
        out = [x for x in out if x['ot'] <= t_to]
    return out


def load_session(sym, market, base_from):
    m1 = json.load(open(f'{HERE}/data/{sym}-1m.json'))
    base5, daily = [], []
    for (t, o, h, l, c) in m1:
        s = session(t, market)
        if s is None:
            continue
        ss, se, k = s
        if market == 'fx' and weekday(k) >= 5:
            continue                      # prints after the Friday 17:00 close
        if daily and daily[-1]['k'] == k:
            x = daily[-1]; x['h'] = max(x['h'], h); x['l'] = min(x['l'], l); x['c'] = c
        else:
            daily.append(dict(ot=ss, ct=se, o=o, h=h, l=l, c=c, k=k))
        if t >= base_from:
            b = t // (5 * MIN) * (5 * MIN)
            if base5 and base5[-1][0] == b:
                x = base5[-1]; x[2] = max(x[2], h); x[3] = min(x[3], l); x[4] = c
            else:
                base5.append([b, o, h, l, c])
    base5 = [tuple(x) for x in base5]
    cache = {}

    def intraday(minutes):
        dur = minutes * MIN
        out = []
        for (t, o, h, l, c) in base5:
            ss, se, k = session(t, market)
            bo = ss + (t - ss) // dur * dur
            if out and out[-1]['ot'] == bo:
                x = out[-1]; x['h'] = max(x['h'], h); x['l'] = min(x['l'], l); x['c'] = c
            else:
                out.append(dict(ot=bo, ct=min(bo + dur, se), o=o, h=h, l=l, c=c))
        return out

    def grouped(tf):
        unit, n = tf[-1], int(tf[:-1] or 1)
        out, last = [], None
        for i, d in enumerate(daily):
            if unit == 'D':
                key = i // n                       # n trading sessions per candle
            elif unit == 'W':
                key = ((d['k'] - weekday(d['k'])) // 7) // n
            else:
                y = dt.date(1970, 1, 1) + dt.timedelta(days=d['k'])
                key = (y.year * 12 + y.month - 1) // n
            if out and key == last:
                x = out[-1]; x['h'] = max(x['h'], d['h']); x['l'] = min(x['l'], d['l']); x['c'] = d['c']; x['ct'] = d['ct']
            else:
                out.append(dict(ot=d['ot'], ct=d['ct'], o=d['o'], h=d['h'], l=d['l'], c=d['c']))
                last = key
        return out

    def candles(tf, t_from=None, t_to=None):
        if tf not in cache:
            cache[tf] = grouped(tf) if tf[-1] in 'DWM' else intraday(int(tf))
        return _clip(cache[tf], t_from, t_to)
    return candles, base5


# ── EMA 200 ───────────────────────────────────────────────────────────────
def ema(bars, n=EMA_LEN):
    out, e, s, a = [None] * len(bars), None, 0.0, 2 / (n + 1)
    for i, b in enumerate(bars):
        if i < n:
            s += b['c']
            if i == n - 1:
                e = s / n; out[i] = e
            continue
        e = a * b['c'] + (1 - a) * e
        out[i] = e
    return out


def rma(vals, n):
    """ta.rma: seeded with the SMA of the first n values, then alpha = 1/n. None until then (and for missing inputs)."""
    out, r, buf = [None] * len(vals), None, []
    for i, v in enumerate(vals):
        if r is None:
            if v is None:
                buf = []
                continue
            buf.append(v)
            if len(buf) == n:
                r = sum(buf) / n; out[i] = r
            continue
        r = (v + (n - 1) * r) / n if v is not None else r
        out[i] = r
    return out


def adx(bars, di_len=ADX_DI_LEN, adx_len=ADX_LEN):
    """ADX as TradingView's built-in 'ADX' / ta.dmi(di_len, adx_len): Wilder (RMA) smoothing of TR, +DM, -DM and DX."""
    n = len(bars)
    tr, pdm, mdm = [None] * n, [None] * n, [None] * n
    for i in range(1, n):
        h, l, pc = bars[i]['h'], bars[i]['l'], bars[i - 1]['c']
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
        up, down = h - bars[i - 1]['h'], bars[i - 1]['l'] - l
        pdm[i] = up if (up > down and up > 0) else 0.0
        mdm[i] = down if (down > up and down > 0) else 0.0
    trr, pr, mr = rma(tr, di_len), rma(pdm, di_len), rma(mdm, di_len)
    dx, plus, minus = [None] * n, None, None
    for i in range(n):
        if trr[i] is None:
            continue
        if trr[i] != 0:                     # fixnan(): a zero true range keeps the previous +DI / -DI
            plus, minus = 100 * pr[i] / trr[i], 100 * mr[i] / trr[i]
        if plus is None:
            continue
        s = plus + minus
        dx[i] = abs(plus - minus) / (s if s != 0 else 1)
    return [None if v is None else 100 * v for v in rma(dx, adx_len)]


# ── signals and trades ────────────────────────────────────────────────────
def signals(candles, t0, t1, mode):
    ref.candles = candles
    p = dict(ref.P)
    p.update(early=False, shiftAll=True)   # settings of the 3-timeframe study
    need = p['needTF']
    groups = [NAMES[j:j + need] for j in range(len(NAMES) - need + 1)]
    runs = [('5', None)] if mode == 'A' else [(TF_OF[g[0]], g) for g in groups]
    sigs = []
    for chart_tf, grp in runs:
        chart, per_tf, fires = ref.mtf(chart_tf, t0, t1, p=p, buf_days=4000, enabled=set(grp) if grp else None)
        idx = {c['ot']: i for i, c in enumerate(chart)}
        pos = {nm: k for k, (_, nm, _, _) in enumerate(per_tf)}
        for (ot, side, gname) in fires:
            ci = idx[ot]
            g = gname.split(' · ')
            st = [per_tf[pos[nm]][3][ci][side] for nm in g]
            sigs.append(dict(mode=mode, group=gname, side=side, ot=chart[ci]['ot'], t=chart[ci]['ct'], entry=chart[ci]['c'],
                             stop=st[-1]['p2'], small=g[0], large=g[-1], osc=st[-1]['osc']))
    return sigs


class TFIndex:
    """Closed-candle lookups (EMA, candle counting) per timeframe."""
    def __init__(self, candles):
        self.candles, self.c = candles, {}
    def get(self, tf):
        if tf not in self.c:
            bars = self.candles(tf)
            self.c[tf] = (bars, [b['ot'] for b in bars], [b['ct'] for b in bars], ema(bars))
        return self.c[tf]
    def ema_at(self, tf, t):
        bars, ots, cts, e = self.get(tf)
        i = bisect.bisect_right(cts, t) - 1
        return e[i] if i >= 0 else None
    def adx_at(self, tf, t):
        """ADX of the last candle of `tf` that closed at or before t."""
        if ('adx', tf) not in self.c:
            self.c[('adx', tf)] = adx(self.get(tf)[0])
        cts, a = self.get(tf)[2], self.c[('adx', tf)]
        i = bisect.bisect_right(cts, t) - 1
        return a[i] if i >= 0 else None
    def limit(self, tf, t):
        bars, ots, cts, _ = self.get(tf)
        i = max(bisect.bisect_right(ots, t) - 1, 0)
        j = i + TIME_LIMIT - 1
        if j < len(bars):
            return cts[j]
        return cts[-1] + (j - len(bars) + 1) * tf_seconds(tf) * 1000


def simulate(sig, bars5, times5, cost_side):
    long = sig['side'] == 'bu'
    E, S = sig['entry'], sig['stop']
    R = (E - S) if long else (S - E)
    if R <= 0:
        return dict(R=R, invalid=True)
    i = bisect.bisect_left(times5, sig['t'])
    mfe, out, last, stopped = 0.0, {1: None, 2: None, 3: None}, E, False
    while i < len(bars5):
        t, o, h, l, c = bars5[i]
        if t >= sig['limit']:
            break
        if (l <= S) if long else (h >= S):
            gap = (o <= S) if long else (o >= S)
            r = min(-1.0, ((o - E) if long else (E - o)) / R) if gap else -1.0
            for k in out:
                if out[k] is None:
                    out[k] = ('loss', r)
            stopped = True
            break
        fav = ((h - E) if long else (E - l)) / R
        if fav > mfe:
            mfe = fav
            for k in out:
                if out[k] is None and mfe >= k:
                    out[k] = ('win', float(k))
        last = c
        i += 1
        if all(v is not None for v in out.values()):
            break
    end_r = ((last - E) if long else (E - last)) / R
    ended = i >= len(bars5) and not stopped
    for k in out:
        if out[k] is None:
            out[k] = ('open' if ended else 'exp', end_r)
    # cost in R for each target outcome
    cost = {k: cost_side * (E + (E + v[1] * R if long else E - v[1] * R)) / R for k, v in out.items()}
    return dict(R=R, riskPct=R / E * 100, out=out, cost=cost, mfe=mfe)


def run(sym):
    market = MARKET[sym]
    if market == 'crypto':
        candles, base5 = load_crypto(sym)
        t0 = int(dt.datetime(2025, 9, 30, tzinfo=dt.timezone.utc).timestamp() * 1000)
        t1 = int(dt.datetime(2026, 9, 29, 23, 55, tzinfo=dt.timezone.utc).timestamp() * 1000)
    else:
        candles, base5 = load_session(sym, market, int(dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000))
        t1 = base5[-1][0]
        t0 = t1 - 365 * DAY
    base5 = [tuple(b) for b in base5]
    times5 = [b[0] for b in base5]
    ix = TFIndex(candles)
    trades = []
    for mode in ('A', 'B'):
        for s in signals(candles, t0, t1, mode):
            if not (t0 <= s['t'] <= t1 + 5 * MIN):
                continue
            s['limit'] = ix.limit(TF_OF[s['large']], s['t'])
            for key, tf in (('emaSmall', TF_OF[s['small']]), ('emaLarge', TF_OF[s['large']]), ('emaD', '1D')):
                s[key] = ix.ema_at(tf, s['ot'])   # last candle closed before the signal candle opened (as in the indicator)
            s.update(sym=sym, market=market, **simulate(s, base5, times5, COST_SIDE[market]))
            trades.append(s)
    pickle.dump(dict(trades=trades, t0=t0, t1=t1), open(f'{HERE}/data/trades_{sym}.pkl', 'wb'))
    print(sym, market, 'signals', len(trades), dt.datetime.utcfromtimestamp(t0 / 1000).date(), '->', dt.datetime.utcfromtimestamp(t1 / 1000).date(), flush=True)


if __name__ == '__main__':
    run(sys.argv[1])
