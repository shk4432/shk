"""Aggregates trades_*.pkl into stats.json (and prints a compact overview)."""
import pickle, json, os, collections
HERE = os.path.dirname(os.path.abspath(__file__))
SYMS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'ZECUSDT', 'HYPEUSDT']
FEE_SIDE = 0.0005
GROUPS = []
names = ['5m', '10m', '15m', '30m', '1H', '2H', '3H', '4H', '6H', '8H', '10H', '12H', '1D', '2D', '3D', '1W', '2W', '3W', '1M']
for j in range(len(names) - 2):
    GROUPS.append(' · '.join(names[j:j + 3]))


def trade_r(t, k, net):
    """Result in R for target k, or None when the trade is still open at the end of the data."""
    o = t['out'][k]
    long = t['side'] == 'bu'
    E, R = t['entry'], t['R']
    if o == 'win':
        r = k
    elif o == 'loss':
        r = -1.0
    elif o[0] == 'exp':
        r = o[1]
    else:
        return None
    if net:
        X = E + r * R if long else E - r * R
        r -= FEE_SIDE * (E + X) / R
    return r


def agg(trs, k, net):
    s = dict(n=0, win=0, loss=0, exp=0, open=0, sumR=0.0)
    for t in trs:
        if t.get('invalid'):
            continue
        s['n'] += 1
        o = t['out'][k]
        r = trade_r(t, k, net)
        if r is None:
            s['open'] += 1
            continue
        if o == 'win': s['win'] += 1
        elif o == 'loss': s['loss'] += 1
        else: s['exp'] += 1
        s['sumR'] += r
    closed = s['win'] + s['loss'] + s['exp']
    s['closed'] = closed
    s['winrate'] = s['win'] / closed * 100 if closed else None
    s['avgR'] = s['sumR'] / closed if closed else None
    return s


def main():
    all_tr = []
    for sym in SYMS:
        all_tr += pickle.load(open(f'{HERE}/data/trades_{sym}.pkl', 'rb'))
    out = dict(rows=[], skipped={})
    idx = collections.defaultdict(list)
    for t in all_tr:
        idx[(t['sym'], t['mode'], t['stop'])].append(t)
    for (sym, mode, stop), trs in idx.items():
        out['skipped'][f'{sym}|{mode}|{stop}'] = sum(1 for t in trs if t.get('invalid'))
        bygrp = collections.defaultdict(list)
        for t in trs:
            bygrp[(t['group'], t['side'])].append(t)
            bygrp[(t['group'], 'all')].append(t)
            bygrp[('ALL', t['side'])].append(t)
            bygrp[('ALL', 'all')].append(t)
        for (g, side), gt in bygrp.items():
            for net in (False, True):
                row = dict(sym=sym, mode=mode, stop=stop, net=net, group=g, side=side)
                for k in (1, 2, 3):
                    row[f'k{k}'] = agg(gt, k, net)
                risks = sorted(t['riskPct'] for t in gt if t.get('riskPct'))
                row['medRiskPct'] = risks[len(risks) // 2] if risks else None
                out['rows'].append(row)
    # every trade for the spreadsheet
    out['trades'] = [dict(sym=t['sym'], mode=t['mode'], stop=t['stop'], group=t['group'], side=t['side'], t=t['t'],
                          entry=t['entry'], stopPrice=t['stopHTF'] if t['stop'] == 'HTF' else t['stopLTF'], R=t['R'],
                          riskPct=t.get('riskPct'), invalid=bool(t.get('invalid')), mfe=t.get('mfe'),
                          out={k: (v if isinstance(v, str) else list(v)) for k, v in (t.get('out') or {}).items()})
                     for t in all_tr]
    json.dump(out, open(f'{HERE}/data/stats.json', 'w'))
    return out


if __name__ == '__main__':
    out = main()
    rows = out['rows']
    def pick(**kw):
        return [r for r in rows if all(r[a] == b for a, b in kw.items())]
    print('== ALL groups, both sides')
    for net in (False, True):
        for mode in 'AB':
            for stop in ('HTF', 'LTF'):
                line = f"net={int(net)} entry={mode} stop={stop}: "
                for sym in SYMS:
                    r = pick(sym=sym, mode=mode, stop=stop, net=net, group='ALL', side='all')[0]
                    a = r['k1']
                    line += f"{sym[:-4]} n{a['n']} wr1 {a['winrate']:.0f}% avg1 {a['avgR']:+.2f} | "
                print(line)
