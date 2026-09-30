"""Download histdata.com 1-minute ASCII bars (EST without DST) -> list of (utc_ms, o, h, l, c)."""
import io, re, sys, json, time, zipfile, urllib.request, urllib.parse, datetime as dt, os
OUT = os.path.dirname(os.path.abspath(__file__)) + '/data'
os.makedirs(OUT, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0'}

def req(url, data=None, ref=None):
    h = dict(UA)
    if ref: h['Referer'] = ref
    for i in range(5):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=120)
            return r.read()
        except Exception as e:
            time.sleep(2 + 2 * i)
    raise RuntimeError('failed ' + url)

def download(pair, year, month=None):
    page = f'https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{pair.lower()}/{year}' + (f'/{month}' if month else '')
    html = req(page).decode('utf8', 'ignore')
    f = dict(re.findall(r'name="(tk|date|datemonth|platform|timeframe|fxpair)" id="\w+" value="([^"]*)"', html))
    if 'tk' not in f:
        return None
    blob = req('https://www.histdata.com/get.php', urllib.parse.urlencode(f).encode(), ref=page)
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        return None
    name = [n for n in z.namelist() if n.endswith('.csv')][0]
    rows = []
    for line in io.TextIOWrapper(z.open(name)):
        p = line.strip().split(';')
        if len(p) < 5: continue
        t = dt.datetime.strptime(p[0], '%Y%m%d %H%M%S').replace(tzinfo=dt.timezone.utc) + dt.timedelta(hours=5)  # EST (no DST) -> UTC
        rows.append((int(t.timestamp() * 1000), float(p[1]), float(p[2]), float(p[3]), float(p[4])))
    return rows

pair = sys.argv[1]
data = {}
for y in range(2021, 2026):
    r = download(pair, y) or []
    for x in r: data[x[0]] = x
    print(pair, y, len(r), flush=True)
for m in range(1, 10):
    r = download(pair, 2026, m) or []
    for x in r: data[x[0]] = x
    print(pair, 2026, m, len(r), flush=True)
out = [data[k] for k in sorted(data)]
json.dump(out, open(f'{OUT}/{pair}-1m.json', 'w'))
print(pair, 'total', len(out), dt.datetime.utcfromtimestamp(out[0][0]/1000), dt.datetime.utcfromtimestamp(out[-1][0]/1000), flush=True)
