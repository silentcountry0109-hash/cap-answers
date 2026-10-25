import pymupdf, re, json
from parse import build, SEMS, pymupdf as _p
VOL = {1: '/mnt/user-data/uploads/歷屆會考題目/第一冊_國中自然_生物篇.pdf',
       2: '/mnt/user-data/uploads/歷屆會考題目/第二冊_國中自然_理化上篇.pdf',
       3: '/mnt/user-data/uploads/歷屆會考題目/第三冊_國中自然_理化下與地科篇.pdf'}
VSEM = {1: ['1上', '1下'], 2: ['2上', '2下'], 3: ['3上', '3下']}
N = lambda t: re.sub(r'\s+', '', t)
def stem_after(text, sub=False):
    t = N(text)
    m = re.match(r'^[（(][^）)]{0,6}[）)]', t)
    if m: t = t[m.end():]
    if sub:
        m = re.match(r'^[（(]\d+[)）]\.?', t); t = t[m.end():] if m else t
    else:
        m = re.match(r'^\d+[.．、]?', t); t = t[m.end():] if m else t
    return t[:14]
report = {}
for v, path in VOL.items():
    vt = N(''.join(p.get_text() for p in pymupdf.open(path)))
    pos = 0; miss = []; total = 0
    for sem in VSEM[v]:
        doc, chs, _ = build(sem)
        for c in chs:
            for it in c['items']:
                entries = []
                if it['type'] == 'q':
                    entries.append((f"{sem} ch{c['ch']} 第{it['num']}題", str(it['num']), stem_after(it['text']), False))
                else:
                    for s in it['subs']:
                        entries.append((f"{sem} ch{c['ch']} 第{it['num']}題({s['num']})", f"({s['num']})", stem_after(s['text'], True), True))
                for label, num, stem, sub in entries:
                    total += 1
                    if not stem:
                        continue
                    pat = re.escape(num) + (r'\.?' if sub else r'[.．、]?') + re.escape(stem[:10])
                    m = re.compile(pat).search(vt, pos)
                    if m and m.start() - pos < 60000:
                        pos = m.end()
                    else:
                        miss.append((label, stem[:12]))
    print(f'第{v}冊：教用作答 {total} 題，於題本中依序找到 {total-len(miss)} 題；未找到 {miss[:10]}')
