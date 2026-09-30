"""Aggregates data/trades_*.pkl (with the EMA 200 filter variants) into report rows and prints an overview."""
import pickle, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
CRYPTO = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'ZECUSDT', 'HYPEUSDT']
TRAD = ['EURUSD', 'GBPUSD', 'XAUUSD', 'SPXUSD', 'NSXUSD']
SYMS = CRYPTO + TRAD
NAMES = ['5m', '10m', '15m', '30m', '1H', '2H', '3H', '4H', '6H', '8H', '10H', '12H', '1D', '2D', '3D', '1W', '2W', '3W', '1M']
GROUPS = [' · '.join(NAMES[j:j + 3]) for j in range(len(NAMES) - 2)]
FILTERS = {'none': None, 'small': 'emaSmall', 'large': 'emaLarge', 'D': 'emaD'}


def load(sym):
    return pickle.load(open(f'{HERE}/data/trades_{sym}.pkl', 'rb'))['trades']


def passes(t, f):
    key = FILTERS[f]
    if key is None:
        return True
    e = t.get(key)
    if e is None:
        return False
    return t['entry'] > e if t['side'] == 'bu' else t['entry'] < e


def agg(trs, k, net):
    n = win = loss = exp = opn = 0
    s = 0.0
    for t in trs:
        if t.get('invalid'):
            continue
        n += 1
        kind, r = t['out'][k]
        if kind == 'open':
            opn += 1
            continue
        if net:
            r -= t['cost'][k]
        s += r
        if kind == 'win': win += 1
        elif kind == 'loss': loss += 1
        else: exp += 1
    closed = win + loss + exp
    return [n, win, loss, exp, opn, round(win / closed * 100, 1) if closed else None, round(s / closed, 3) if closed else None]


def med_risk(trs):
    r = sorted(t['riskPct'] for t in trs if not t.get('invalid'))
    return round(r[len(r) // 2], 2) if r else None


def build():
    trades = {sym: load(sym) for sym in SYMS}
    rows = []
    for sym in SYMS + ['CRYPTO', 'TRAD']:
        pool = trades[sym] if sym in trades else [t for s in (CRYPTO if sym == 'CRYPTO' else TRAD) for t in trades[s]]
        for mode in 'AB':
            pm = [t for t in pool if t['mode'] == mode]
            for f in FILTERS:
                pf = [t for t in pm if passes(t, f)]
                for g in GROUPS + ['ALL']:
                    pg = pf if g == 'ALL' else [t for t in pf if t['group'] == g]
                    for side in ('all', 'bu', 'be'):
                        ps = pg if side == 'all' else [t for t in pg if t['side'] == side]
                        if not ps and g != 'ALL':
                            continue
                        mr = med_risk(ps)
                        for net in (0, 1):
                            rows.append([sym, mode, f, net, g, side, mr] + [agg(ps, k, net) for k in (1, 2, 3)])
    return rows


if __name__ == '__main__':
    rows = build()
    json.dump(dict(groups=GROUPS, rows=rows), open(f'{HERE}/data/report_data.json', 'w'), separators=(',', ':'))
    print('rows', len(rows), os.path.getsize(f'{HERE}/data/report_data.json'))
    ix = {tuple(r[:6]): r for r in rows}
    for mode in 'A':
        for net in (0, 1):
            print(f'\n== entry {mode}, {"with costs" if net else "no costs"}: n / 1R win% avgR / 2R avgR / 3R avgR')
            print(f"{'symbol':9s}" + ''.join(f'| {f:^34s}' for f in FILTERS))
            for sym in SYMS + ['CRYPTO', 'TRAD']:
                line = f'{sym:9s}'
                for f in FILTERS:
                    r = ix[(sym, mode, f, net, 'ALL', 'all')]
                    a, b, c = r[7], r[8], r[9]
                    fmt = lambda v: '  -  ' if v is None else f'{v:+.2f}'
                    line += f"| {a[0]:5d} {a[5] if a[5] is not None else 0:5.1f}% {fmt(a[6])} {fmt(b[6])} {fmt(c[6])} "
                print(line)
