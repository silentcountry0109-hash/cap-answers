import pymupdf, re, json, collections
VOL = {1: '/mnt/user-data/uploads/歷屆會考題目/第一冊_國中自然_生物篇.pdf',
       2: '/mnt/user-data/uploads/歷屆會考題目/第二冊_國中自然_理化上篇.pdf',
       3: '/mnt/user-data/uploads/歷屆會考題目/第三冊_國中自然_理化下與地科篇.pdf'}
VSEM = {1: ['1上', '1下'], 2: ['2上', '2下'], 3: ['3上', '3下']}
def norm(t):
    t = re.sub(r'\s+', '', t)
    return t
def shingles(t, k=6):
    return set(t[i:i+k] for i in range(0, max(0, len(t)-k+1)))
def page_text(p, clip=None):
    return norm(p.get_text(clip=clip) if clip else p.get_text())
res = {}
for v, path in VOL.items():
    vd = pymupdf.open(path)
    src = []
    for sem in VSEM[v]:
        d = pymupdf.open(f'/home/claude/work/src/{sem}_學用.pdf')
        for i, p in enumerate(d):
            # exclude footer page number
            src.append((sem, i+1, shingles(page_text(p, pymupdf.Rect(0, 0, p.rect.width, 772)))))
    mapping = []
    for vi, vp in enumerate(vd):
        vt = page_text(vp, pymupdf.Rect(0, 50, vp.rect.width, 770))
        vs = shingles(vt)
        if len(vt) < 40:
            mapping.append((vi+1, None, 0)); continue
        best = max(src, key=lambda s: len(vs & s[2]) / (len(vs | s[2]) or 1))
        sc = len(vs & best[2]) / (len(vs | best[2]) or 1)
        mapping.append((vi+1, (best[0], best[1]) if sc > 0.3 else None, round(sc, 2)))
    used = [m[1] for m in mapping if m[1]]
    allsrc = [(s[0], s[1]) for s in src]
    missing = [s for s in allsrc if s not in used]
    dups = [k for k, c in collections.Counter(used).items() if c > 1]
    order_ok = used == sorted(used, key=lambda s: allsrc.index(s))
    unmapped = [(m[0], m[2]) for m in mapping if not m[1]]
    lowsc = [(m[0], m[1], m[2]) for m in mapping if m[1] and m[2] < 0.8]
    print(f'第{v}冊: {len(vd)} 頁；對應教用頁 {len(used)}/{len(allsrc)}；缺 {missing}；重複 {dups}；順序一致 {order_ok}')
    print('   非試題頁(封面/目次/分隔):', [u[0] for u in unmapped])
    print('   相似度<0.8:', lowsc[:20])
    res[v] = mapping
json.dump(res, open('/home/claude/work/data/vol_map_xueyong.json', 'w'), ensure_ascii=False)
