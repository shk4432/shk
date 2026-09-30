"""Python implementation of the indicator's divergence logic (checked bar-for-bar against the Pine script)."""
import json, math, datetime as dt

MIN, DAY = 60_000, 86_400_000
WEEK, MON_OFF = 7 * DAY, 4 * DAY
NA = float('nan')

candles = None   # candle source: set by the caller, e.g. backtest.make_candles()

P = dict(rsiLen=14, momLen=9, fastRsiLen=3, fastSmaLen=3, mode='CI', minDist=5, maxDist=40, pivL=5, pivR=2,
         useClose=False, early=True, useRegular=True, useHidden=False, strictPx=True, strictOsc=False, validBars=20, needTF=3, syncOn=True, syncTol=1, groups='up')

LADDER = [('5', '5m'), ('10', '10m'), ('15', '15m'), ('30', '30m'), ('60', '1H'), ('120', '2H'), ('180', '3H'), ('240', '4H'),
          ('360', '6H'), ('480', '8H'), ('600', '10H'), ('720', '12H'), ('1D', '1D'), ('2D', '2D'), ('3D', '3D'),
          ('1W', '1W'), ('2W', '2W'), ('3W', '3W'), ('1M', '1M')]


def tf_seconds(tf):
    u = tf[-1]
    if u in 'DWM':
        m = int(tf[:-1] or 1)
        return m * {'D': 86400, 'W': 604800, 'M': 2592000}[u]  # PineTS uses 30-day months
    return int(tf) * 60




def bucket(t, tf):
    u = tf[-1] if tf[-1] in 'DWM' else ''
    mult = int(tf[:-1] or 1) if u else int(tf)
    if u == '':
        dur = mult * MIN; day = t // DAY * DAY
        o = day + (t - day) // dur * dur
        return o, min(o + dur, day + DAY)
    if u == 'D':
        dur = mult * DAY; o = t // dur * dur; return o, o + dur
    if u == 'W':
        dur = mult * WEEK; o = (t - MON_OFF) // dur * dur + MON_OFF; return o, o + dur
    d = dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc)
    mo = d.year * 12 + d.month - 1
    s = mo // mult * mult
    f = lambda m: int(dt.datetime(m // 12, m % 12 + 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    return f(s), f(s + mult)




def rma(x, n):
    out = [NA] * len(x); s = []; prev = NA
    for i, v in enumerate(x):
        if math.isnan(v):
            continue
        if math.isnan(prev):
            s.append(v)
            if len(s) == n:
                prev = sum(s) / n; out[i] = prev
        else:
            prev = (v + (n - 1) * prev) / n; out[i] = prev
    return out


def rsi(close, n):
    up = [NA] + [max(close[i] - close[i - 1], 0) for i in range(1, len(close))]
    dn = [NA] + [max(close[i - 1] - close[i], 0) for i in range(1, len(close))]
    ru, rd = rma(up, n), rma(dn, n)
    out = []
    for a, b in zip(ru, rd):
        if math.isnan(a) or math.isnan(b):
            out.append(NA)
        elif b == 0:
            out.append(100.0)
        elif a == 0:
            out.append(0.0)
        else:
            out.append(100 - 100 / (1 + a / b))
    return out


def sma(x, n):
    out = [NA] * len(x)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        if not any(math.isnan(v) for v in w):
            out[i] = sum(w) / n
    return out


def pivots(src, L, R, low):
    out = [NA] * len(src)
    for i in range(L + R, len(src)):
        p = src[i - R]; ok = True
        for j in range(1, L + 1):
            v = src[i - R - j]
            if (v < p) if low else (v > p):
                ok = False; break
        if ok:
            for j in range(1, R + 1):
                v = src[i - R + j]
                if (v <= p) if low else (v >= p):
                    ok = False; break
        if ok:
            out[i] = p
    return out


def line_clear(ser, i2, d, v1, v2, above):
    # ser indexed by bar; i2 = bar of the second point
    for k in range(1, d):
        lv = v2 + (v1 - v2) * k / d
        sv = ser[i2 - k]
        if math.isnan(sv):
            continue
        if sv != v1 and sv != v2 and ((sv < lv) if above else (sv > lv)):
            return False
    return True


def scan(bars, p=P):
    """Per-bar divergence state (NOT shifted). Returns list of dicts {bu:..., be:...}."""
    c = [b['c'] for b in bars]
    lo = c if p['useClose'] else [b['l'] for b in bars]
    hi = c if p['useClose'] else [b['h'] for b in bars]
    r = rsi(c, p['rsiLen'])
    rf = rsi(c, p['fastRsiLen'])
    ci = [NA if (i < p['momLen'] or math.isnan(r[i]) or math.isnan(r[i - p['momLen']])) else r[i] - r[i - p['momLen']] for i in range(len(c))]
    ci = [a + b for a, b in zip(ci, sma(rf, p['fastSmaLen']))]
    pl = pivots(lo, p['pivL'], p['pivR'], True)
    ph = pivots(hi, p['pivL'], p['pivR'], False)
    R = p['pivR']
    L = p['pivL']
    early = p.get('early', False)
    # early timing: the candle is the low (high) of itself and the L candles before it
    new_low = [early and i >= L and lo[i] <= min(lo[i - L:i]) for i in range(len(bars))]
    new_high = [early and i >= L and hi[i] >= max(hi[i - L:i]) for i in range(len(bars))]
    off = 0 if early else R
    life = max(p['validBars'], R + 1)
    st = {s: dict(on=False, b2=None, t1=None, p1=None, t2=None, p2=None, osc=0, hid=False) for s in ('bu', 'be')}
    piv = {'bu': [], 'be': []}  # newest first: (bar, time, price, rsi, ci)
    out = []
    for i in range(len(bars)):
        for side, pv, px in (('bu', pl, lo), ('be', ph, hi)):
            isBull = side == 'bu'
            cand = (new_low[i] if isBull else new_high[i]) if early else not math.isnan(pv[i])
            if not cand:
                if not math.isnan(pv[i]):   # confirmed swing points are the first-swing candidates
                    piv[side].insert(0, (i - R, bars[i - R]['ot'], pv[i], r[i - R], ci[i - R]))
                    del piv[side][p['maxDist'] + 1:]
                continue
            b2 = i - off; t2 = bars[b2]['ot']; p2 = px[b2]; r2 = r[b2]; c2 = ci[b2]
            match = None
            if not (math.isnan(r2) or math.isnan(c2)):
                for (b1, t1, p1, r1, c1) in piv[side]:
                    d = b2 - b1
                    if d > p['maxDist']:
                        break
                    regular = p2 < p1 if isBull else p2 > p1
                    hidden = p2 > p1 if isBull else p2 < p1
                    if d >= p['minDist'] and not math.isnan(r1) and not math.isnan(c1) and ((p['useRegular'] and regular) or (p['useHidden'] and hidden)):
                        up = p2 > p1
                        ciDiv = c2 < c1 if up else c2 > c1
                        rsDiv = r2 < r1 if up else r2 > r1
                        pxOK = True
                        if p['strictPx']:
                            pxOK = line_clear(px, b2, d, p1, p2, isBull)
                        if p['strictOsc']:
                            ciDiv = ciDiv and line_clear(ci, b2, d, c1, c2, isBull)
                            rsDiv = rsDiv and line_clear(r, b2, d, r1, r2, isBull)
                        oscOK = {'CI': ciDiv, 'BOTH': ciDiv and rsDiv, 'ANY': ciDiv or rsDiv, 'RSI': rsDiv}[p['mode']]
                        if pxOK and oscOK:
                            match = (t1, p1, (1 if ciDiv else 0) + (2 if rsDiv else 0), hidden)
                            break
            s = st[side]
            if match:
                s.update(on=True, b2=b2, t1=match[0], p1=match[1], t2=t2, p2=p2, osc=match[2], hid=match[3])
            elif s['on'] and ((p2 < s['p2']) if isBull else (p2 > s['p2'])):
                s['on'] = False
            if not math.isnan(pv[i]):
                piv[side].insert(0, (i - R, bars[i - R]['ot'], pv[i], r[i - R], ci[i - R]))
                del piv[side][p['maxDist'] + 1:]
        for side in ('bu', 'be'):
            s = st[side]
            if s['on'] and (i - s['b2'] > life or ((c[i] < s['p2']) if side == 'bu' else (c[i] > s['p2']))):
                s['on'] = False
        out.append({side: dict(st[side], age=(i - st[side]['b2']) if st[side]['b2'] is not None else None) for side in st})
    return out


def shifted(states):
    off = dict(on=False, b2=None, t1=None, p1=None, t2=None, p2=None, osc=0, hid=False, age=None)
    return [{'bu': off, 'be': off}] + states[:-1]


def mtf(chart_tf, t_from, t_to, ladder=LADDER, p=P, buf_days=30, enabled=None):
    """Returns chart bars, per-bar ladder states, and fired signals like the Pine script."""
    chart = candles(chart_tf, t_from, t_to)
    csec = tf_seconds(chart_tf)
    lad = [(tf, nm) for tf, nm in ladder if enabled is None or nm in enabled]
    per_tf = []
    for tf, nm in lad:
        bars = candles(tf, t_from - buf_days * DAY, t_to)
        raw = scan(bars, p)
        sh = shifted(raw) if (tf_seconds(tf) > csec or p.get('shiftAll')) else raw
        lower = tf_seconds(tf) < csec
        vals = []
        j = 0
        for cb in chart:
            if lower:
                # last TF bar fully inside the chart bar
                idx = None
                while j < len(bars) and bars[j]['ot'] < cb['ot']:
                    j += 1
                k = j
                while k < len(bars) and bars[k]['ct'] <= cb['ct'] and bars[k]['ot'] >= cb['ot']:
                    idx = k; k += 1
                vals.append(sh[idx] if idx is not None else None)
            else:
                while j + 1 < len(bars) and bars[j + 1]['ot'] <= cb['ot']:
                    j += 1
                ok = bars and bars[j]['ot'] <= cb['ot'] < bars[j]['ct']
                vals.append(sh[j] if ok else None)
        # hold the last known state when a chart bar has no data for this TF (or no divergence yet)
        off = dict(on=False, b2=None, t1=None, p1=None, t2=None, p2=None, osc=0, hid=False, age=None)
        held = {'bu': off, 'be': off}; hv = []
        for v in vals:
            for side in ('bu', 'be'):
                if v is not None and v[side]['t2'] is not None:
                    held[side] = v[side]
            hv.append(dict(held))
        per_tf.append((tf, nm, tf_seconds(tf), hv))
    n = len(per_tf); need = p['needTF']
    prev = {'bu': [False] * 19, 'be': [False] * 19}
    fired = {'bu': [0] * 19, 'be': [0] * 19}
    fires = []
    for ci_, cb in enumerate(chart):
        for side in ('bu', 'be'):
            for j in range(0, n - need + 1):
                ok = True; hi = 0; anchor = None
                for k in range(j, j + need):
                    d = per_tf[k][3][ci_]
                    if d is None or not d[side]['on']:
                        ok = False; break
                    if per_tf[k][2] > hi:
                        hi = per_tf[k][2]; anchor = d[side]['t2']
                if ok and p['syncOn']:
                    w = hi * 1000
                    for k in range(j, j + need):
                        t2 = per_tf[k][3][ci_][side]['t2']
                        if t2 < anchor - p['syncTol'] * w or t2 >= anchor + (1 + p['syncTol']) * w:
                            ok = False; break
                shown = p['groups'] == 'all' or per_tf[j][2] >= csec
                if ok and not prev[side][j] and fired[side][j] != anchor and shown:
                    fired[side][j] = anchor
                    fires.append((cb['ot'], side, ' · '.join(per_tf[k][1] for k in range(j, j + need))))
                prev[side][j] = ok
    return chart, per_tf, fires

