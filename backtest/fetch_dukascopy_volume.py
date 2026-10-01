"""Download Dukascopy BID candle volumes for the AVWAP filter (histdata.com candles have no volume).

  data/{SYM}-vol1h.json : hourly volumes 2021 -> 2026-09, for daily and higher candles
                          (the 17:00 New York session boundary always falls on a full hour)
  data/{SYM}-vol1m.json : 1-minute volumes 2025 -> 2026-09, for the intraday candles
Rows are [utc_ms, volume, close]; the close is only used to check the time alignment against histdata.
Raw files are cached in data/duka/, so an interrupted run resumes.
"""
import os, sys, json, lzma, struct, time, datetime as dt, urllib.request
from concurrent.futures import ThreadPoolExecutor
OUT = os.path.dirname(os.path.abspath(__file__)) + '/data'
POINT = {'EURUSD': 1e-5, 'GBPUSD': 1e-5, 'XAUUSD': 1e-3}
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
HOURS_FROM, MINUTES_FROM, END = dt.date(2021, 1, 1), dt.date(2025, 1, 1), dt.date(2026, 9, 26)


def get(url):
    for i in range(12):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b''
        except Exception:
            pass
        time.sleep(min(2 ** i, 30))
    raise RuntimeError('failed ' + url)


def cached(sym, name, url):
    path = f'{OUT}/duka/{sym}/{name}.bi5'
    if os.path.exists(path):
        blob = open(path, 'rb').read()
        try:
            if blob:
                lzma.decompress(blob)
            return blob
        except lzma.LZMAError:
            pass                                    # truncated by an interrupted run: download again
    blob = get(url)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path + '.part', 'wb').write(blob)
    os.replace(path + '.part', path)
    return blob


def parse(sym, blob, t0):
    if not blob:
        return []
    raw = lzma.decompress(blob)
    out = []
    for i in range(0, len(raw), 24):
        sec, o, c, lo, hi, vol = struct.unpack('>5if', raw[i:i + 24])
        if vol > 0:
            out.append([t0 + sec * 1000, round(vol, 6), round(c * POINT[sym], 6)])
    return out


def utc_ms(y, m, d=1):
    return int(dt.datetime(y, m, d, tzinfo=dt.timezone.utc).timestamp() * 1000)


def month(sym, y, m):
    # the month in Dukascopy URLs is 0-based
    blob = cached(sym, f'{y}-{m:02d}-hours', f'https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m - 1:02d}/BID_candles_hour_1.bi5')
    return parse(sym, blob, utc_ms(y, m))


def day(sym, d):
    blob = cached(sym, str(d), f'https://datafeed.dukascopy.com/datafeed/{sym}/{d.year}/{d.month - 1:02d}/{d.day:02d}/BID_candles_min_1.bi5')
    return parse(sym, blob, utc_ms(d.year, d.month, d.day))


def run(fn, jobs, threads):
    with ThreadPoolExecutor(threads) as ex:
        parts = list(ex.map(fn, jobs))
    return sorted(r for p in parts for r in p)


def fetch(sym):
    months = [(y, m) for y in range(HOURS_FROM.year, END.year + 1) for m in range(1, 13) if (y, m) <= (END.year, END.month)]
    days = [MINUTES_FROM + dt.timedelta(days=i) for i in range((END - MINUTES_FROM).days + 1)]
    days = [d for d in days if d.weekday() != 5]          # no trading on Saturdays
    threads = int(os.environ.get('THREADS', '8'))
    end = utc_ms(END.year, END.month, END.day)
    hours = [r for r in run(lambda ym: month(sym, *ym), months, threads) if r[0] < end]
    json.dump(hours, open(f'{OUT}/{sym}-vol1h.json', 'w'))
    minutes = run(lambda d: day(sym, d), days, threads)
    json.dump(minutes, open(f'{OUT}/{sym}-vol1m.json', 'w'))
    for name, rows in (('hours', hours), ('minutes', minutes)):
        print(sym, name, len(rows), dt.datetime.utcfromtimestamp(rows[0][0] / 1000), '->', dt.datetime.utcfromtimestamp(rows[-1][0] / 1000), flush=True)


if __name__ == '__main__':
    fetch(sys.argv[1])
