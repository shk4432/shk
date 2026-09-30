"""Download Binance 5m (last ~14 months) and 1d (full history) klines from data.binance.vision."""
import io, os, sys, zipfile, csv, json, urllib.request, datetime as dt
OUT = os.path.dirname(os.path.abspath(__file__)) + '/data'
os.makedirs(OUT, exist_ok=True)
BASE = 'https://data.binance.vision/data'
SYMS = {'BTCUSDT': 'spot', 'ETHUSDT': 'spot', 'SOLUSDT': 'spot', 'ZECUSDT': 'spot', 'HYPEUSDT': 'futures/um'}
END = dt.date(2026, 9, 29)

def get(url):
    for i in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:
            pass
    return None

def rows(blob):
    z = zipfile.ZipFile(io.BytesIO(blob))
    out = []
    for line in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
        if not line or not line[0].isdigit():
            continue
        t = int(line[0])
        if t > 10**14:          # spot files switched to microseconds in 2025
            t //= 1000
        out.append((t, float(line[1]), float(line[2]), float(line[3]), float(line[4])))
    return out

def months(a, b):
    y, m = a.year, a.month
    while (y, m) <= (b.year, b.month):
        yield f'{y}-{m:02d}'
        m += 1
        if m == 13: y, m = y + 1, 1

def fetch(sym, market, interval, start):
    data = {}
    last_full = (END.replace(day=1) - dt.timedelta(days=1))
    for mo in months(start, last_full):
        b = get(f'{BASE}/{market}/monthly/klines/{sym}/{interval}/{sym}-{interval}-{mo}.zip')
        if b:
            for r in rows(b): data[r[0]] = r
    d = END.replace(day=1)
    while d <= END:
        b = get(f'{BASE}/{market}/daily/klines/{sym}/{interval}/{sym}-{interval}-{d}.zip')
        if b:
            for r in rows(b): data[r[0]] = r
        d += dt.timedelta(days=1)
    out = [data[k] for k in sorted(data)]
    json.dump(out, open(f'{OUT}/{sym}-{interval}.json', 'w'))
    print(sym, interval, len(out), dt.datetime.utcfromtimestamp(out[0][0]/1000) if out else None, dt.datetime.utcfromtimestamp(out[-1][0]/1000) if out else None, flush=True)

sym = sys.argv[1]
fetch(sym, SYMS[sym], '1d', dt.date(2017, 1, 1))
fetch(sym, SYMS[sym], '5m', dt.date(2025, 7, 1))
