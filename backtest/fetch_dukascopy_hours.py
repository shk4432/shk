"""Download Dukascopy hourly BID candles before the histdata.com minutes (2003 -> 2020) for long daily history.

The daily and higher candles need years of history (EMA 200 on a weekly chart = 4 years); histdata.com minutes
start in 2021. Dukascopy hours give the same prices (the histdata minute closing each hour matches the Dukascopy
hourly close in 97% of the hours 2021-2026) and their hours never straddle the 17:00 New York session boundary.
Output: data/{SYM}-1h.json = [[utc_ms, o, h, l, c, volume], ...]
"""
import os, sys, json, lzma, struct, datetime as dt
from fetch_dukascopy_volume import OUT, POINT, cached, utc_ms, run
FROM, TO = (2003, 1), (2020, 12)


def month(sym, y, m):
    blob = cached(sym, f'{y}-{m:02d}-hours', f'https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m - 1:02d}/BID_candles_hour_1.bi5')
    if not blob:
        return []
    raw, t0, p = lzma.decompress(blob), utc_ms(y, m), POINT[sym]
    out = []
    for i in range(0, len(raw), 24):
        sec, o, c, lo, hi, vol = struct.unpack('>5if', raw[i:i + 24])
        if vol > 0:                                   # Dukascopy fills closed hours with flat zero-volume candles
            out.append([t0 + sec * 1000, round(o * p, 6), round(hi * p, 6), round(lo * p, 6), round(c * p, 6), round(vol, 6)])
    return out


if __name__ == '__main__':
    sym = sys.argv[1]
    months = [(y, m) for y in range(FROM[0], TO[0] + 1) for m in range(1, 13) if FROM <= (y, m) <= TO]
    rows = run(lambda ym: month(sym, *ym), months, int(os.environ.get('THREADS', '8')))
    json.dump(rows, open(f'{OUT}/{sym}-1h.json', 'w'))
    print(sym, len(rows), 'hours', dt.datetime.utcfromtimestamp(rows[0][0] / 1000), '->', dt.datetime.utcfromtimestamp(rows[-1][0] / 1000), flush=True)
