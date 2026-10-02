"""Statistics of the four improvement ideas: data/improve_5y_*.pkl -> results/improve_5y.csv (+ terciles).

Rows: idea, variant, symbol (and all three), period, target. Periods: all five years, years 1-3 and years 4-5
(the variants were fixed before looking at any result, so both halves are a test of them).
'win' = the trade ended above zero (with a partial close: the half closed at 1R counts), 'be' = closed at the entry.
Losing streak = consecutive trades closed below zero before costs (a trade closed at the entry breaks it).
"""
import os, csv, pickle, statistics as st, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
SYMS = ['BTCUSDT', 'EURUSD', 'XAUUSD']


def load():
    out = {}
    for s in SYMS:
        d = pickle.load(open(f'{HERE}/data/improve_5y_{s}.pkl', 'rb'))
        t0 = dt.datetime.fromtimestamp(d['t0'] / 1000, dt.timezone.utc)
        edges = [int(t0.replace(year=t0.year + y).timestamp() * 1000) for y in range(1, 6)]
        for t in d['trades']:
            t['year'] = 1 + sum(1 for e in edges if t['t'] >= e)
        out[s] = d['trades']
    return out


def toward(t):
    """RSI at point 2 measured toward the trade: buy = RSI, sell = 100 - RSI (lower = more oversold/overbought)."""
    return t['feat']['r2'] if t['side'] == 'bu' else 100 - t['feat']['r2']


def with_trend_daily(t):
    e = t['feat']['ema_daily']
    return e is not None and (t['entry'] > e if t['side'] == 'bu' else t['entry'] < e)


def with_slope(t):
    s = t['feat']['ema_slope']
    return s > 0 if t['side'] == 'bu' else s < 0


# (idea, variant, label, trade selector, simulation)
VARIANTS = [
    ('base', 'base', 'Current setup', None, 'plain'),
    ('1 manage', 'half1', 'Half at 1R, stop to entry', None, 'half1'),
    ('1 manage', 'be05', 'Stop to entry at +0.5R', None, 'be05'),
    ('2 buffer', 'buf0.25', 'Stop + 0.25 ATR', None, 'buf0.25'),
    ('2 buffer', 'buf0.5', 'Stop + 0.5 ATR', None, 'buf0.5'),
    ('3 quality', 'rsi40', 'RSI at point 2: buy < 40, sell > 60', lambda t: toward(t) < 40, 'plain'),
    ('3 quality', 'rsi35', 'RSI at point 2: buy < 35, sell > 65', lambda t: toward(t) < 35, 'plain'),
    ('3 quality', 'diff5', 'RSI difference between points >= 5', lambda t: abs(t['feat']['r1'] - t['feat']['r2']) >= 5, 'plain'),
    ('3 quality', 'dist10', 'Distance between points >= 10 candles', lambda t: t['feat']['dist'] >= 10, 'plain'),
    ('4 trend', 'daily', 'Daily EMA 200 on the same side too', with_trend_daily, 'plain'),
    ('4 trend', 'slope', 'Own EMA 200 sloping the trade way', with_slope, 'plain'),
]
PERIODS = (('1-5', lambda y: True), ('1-3', lambda y: y <= 3), ('4-5', lambda y: y >= 4))


def pick(trades, sel, sim, k):
    """(trade, result) pairs of one variant and target."""
    out = []
    for t in trades:
        if sel is not None and not sel(t):
            continue
        o = t['sims'].get((sim, k))
        if o is not None:
            out.append((t, o))
    return out


def stats(pairs, nd=4):
    """nd: decimals of the R figures (None = unrounded, for reports that round again)."""
    rnd = (lambda x: x) if nd is None else (lambda x: round(x, nd))
    n = len(pairs)
    closed = [(t, o) for t, o in pairs if o['kind'] != 'open']
    m = len(closed)
    if not m:
        return [n, 0, None, None, None, None, None, None, None, None, None]
    net = [o['r'] - o['cost'] for _, o in closed]
    gross = [o['r'] for _, o in closed]
    win = sum(1 for _, o in closed if o['kind'] == 'win')
    be = sum(1 for _, o in closed if o['kind'] == 'be')
    loss = m - win - be
    ci = 1.96 * st.pstdev(net) / m ** 0.5 if m > 1 else None
    cum = peak = dd = 0.0
    streak = longest = 0
    for t, o in sorted(closed, key=lambda p: (p[1]['exit_t'], p[0]['t'])):
        r = o['r'] - o['cost']
        cum += r; peak = max(peak, cum); dd = max(dd, peak - cum)
        streak = streak + 1 if o['kind'] == 'loss' else 0     # a trade closed at the entry does not count as a loss
        longest = max(longest, streak)
    return [n, n - m, round(win / m * 100, 1), round(be / m * 100, 1), round(loss / m * 100, 1),
            rnd(sum(gross) / m), rnd(sum(net) / m), None if ci is None else rnd(ci),
            round(sum(net), 2), round(dd, 2), longest]


def rows(data, nd=4):
    out = []
    for idea, var, label, sel, sim in VARIANTS:
        for sym in SYMS + ['ALL']:
            pool = data[sym] if sym != 'ALL' else [t for s in SYMS for t in data[s]]
            for pname, pf in PERIODS:
                pp = [t for t in pool if pf(t['year'])]
                for k in (1, 2, 3):
                    pairs = pick(pp, sel, sim, k)
                    if sim == 'half1' and k == 1:
                        continue
                    s = stats(pairs, nd)
                    out.append([idea, var, label, sym, pname, f'{k}R'] + s)
    return out


def terciles(data, nd=4):
    """Diagnostic: the current setup split into three equal groups by each divergence measure."""
    pool = [t for s in SYMS for t in data[s] if ('plain', 2) in t['sims']]
    meas = (('RSI at point 2 toward the trade', toward),
            ('RSI difference between points', lambda t: abs(t['feat']['r1'] - t['feat']['r2'])),
            ('Distance between points (candles)', lambda t: t['feat']['dist']))
    out = []
    for name, fn in meas:
        srt = sorted(pool, key=fn)
        n = len(srt)
        for g in range(3):
            part = srt[g * n // 3:(g + 1) * n // 3]
            lo, hi = fn(part[0]), fn(part[-1])
            row = [name, g + 1, round(lo, 1), round(hi, 1)]
            for k in (1, 2, 3):
                s = stats([(t, t['sims'][('plain', k)]) for t in part], nd)
                row += [s[0], s[2], s[6]]
            for pname, pf in PERIODS[1:]:
                s = stats([(t, t['sims'][('plain', 2)]) for t in part if pf(t['year'])], nd)
                row += [s[0], s[6]]
            out.append(row)
    return out


if __name__ == '__main__':
    data = load()
    with open(f'{HERE}/results/improve_5y.csv', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['idea', 'variant', 'description', 'symbol', 'years', 'target', 'trades', 'open', 'win_pct', 'breakeven_pct',
                    'loss_pct', 'avg_R_gross', 'avg_R_net', 'ci95_net', 'total_R_net', 'max_drawdown_R', 'longest_losing_streak'])
        w.writerows(rows(data))
    with open(f'{HERE}/results/improve_5y_terciles.csv', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['measure', 'group', 'from', 'to', 'trades', '1R_win_pct', '1R_avg_net', 'trades', '2R_win_pct', '2R_avg_net',
                    'trades', '3R_win_pct', '3R_avg_net', 'years_1_3_trades', 'years_1_3_2R_net', 'years_4_5_trades', 'years_4_5_2R_net'])
        w.writerows(terciles(data))
    print('written results/improve_5y.csv and results/improve_5y_terciles.csv')
