"""Aggregates data/trades_tf_*.pkl (per-timeframe signals, no time limit) into report rows and prints an overview."""
import pickle, json, os, sys, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__))
SYMS = ['BTCUSDT', 'EURUSD', 'XAUUSD']
RUN = sys.argv[1] if len(sys.argv) > 1 else 'early2'   # e.g. early2, conf2, conf1
TFS = ['5m', '10m', '15m', '30m', '1H', '2H', '3H', '4H', '6H', '8H', '10H', '12H', '1D', '2D', '3D', '1W', '2W', '3W', '1M']


def load(sym):
    return pickle.load(open(f'{HERE}/data/trades_tf_{RUN}_{sym}.pkl', 'rb'))['trades']


def passes(t, f):
    if f == 'none':
        return True
    e = t.get('ema')
    if e is None:
        return False
    return t['entry'] > e if t['side'] == 'bu' else t['entry'] < e


def agg(trs, k, net):
    n = win = loss = opn = 0
    rs, hold = [], []
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
        rs.append(r)
        if kind == 'win': win += 1
        else: loss += 1
        hold.append((t['exit_t'][k] - t['t']) / 86400000)
    closed = win + loss
    avg = sum(rs) / closed if closed else None
    ci = 1.96 * st.pstdev(rs) / closed ** 0.5 if closed > 1 else None
    return [n, win, loss, opn, round(win / closed * 100, 1) if closed else None,
            None if avg is None else round(avg, 3), None if ci is None else round(ci, 3),
            round(st.median(hold), 2) if hold else None]


def build():
    trades = {s: load(s) for s in SYMS}
    rows = []
    for sym in SYMS + ['ALL']:
        pool = trades[sym] if sym in trades else [t for s in SYMS for t in trades[s]]
        for f in ('none', 'ema'):
            pf = [t for t in pool if passes(t, f)]
            for tf in TFS + ['ALL']:
                pt = pf if tf == 'ALL' else [t for t in pf if t['tf'] == tf]
                for side in ('all', 'bu', 'be'):
                    ps = pt if side == 'all' else [t for t in pt if t['side'] == side]
                    risk = sorted(t['riskPct'] for t in ps if not t.get('invalid'))
                    med = round(risk[len(risk) // 2], 3) if risk else None
                    for net in (0, 1):
                        rows.append([sym, f, net, tf, side, med] + [agg(ps, k, net) for k in (1, 2, 3)])
    return rows


if __name__ == '__main__':
    rows = build()
    json.dump(dict(tfs=TFS, rows=rows), open(f'{HERE}/data/report_tf_{RUN}.json', 'w'), separators=(',', ':'))
    print('rows', len(rows), os.path.getsize(f'{HERE}/data/report_tf_{RUN}.json'))
    ix = {tuple(r[:5]): r for r in rows}
    for sym in SYMS:
        for f in ('none', 'ema'):
            print(f'\n### {sym} filter={f}  (n | risk% | 1R win% avg gross/net ±CI | 2R win% avg net | 3R win% avg net | open1 | hold1 days)')
            for tf in TFS + ['ALL']:
                g = ix[(sym, f, 0, tf, 'all')]; nt = ix[(sym, f, 1, tf, 'all')]
                a = g[6]
                if a[0] == 0:
                    continue
                fm = lambda v: '   -  ' if v is None else f'{v:+.2f}'
                print(f"{tf:4s} {a[0]:5d} {g[5] or 0:6.2f}% | {a[4] or 0:5.1f}% {fm(a[5])}/{fm(nt[6][5])} ±{nt[6][6] or 0:.2f} | {g[7][4] or 0:5.1f}% {fm(nt[7][5])} | {g[8][4] or 0:5.1f}% {fm(nt[8][5])} | {a[3]:3d} | {a[7]}")
