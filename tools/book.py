"""Align 教用 items to the printed book's numbering.

The printed volumes are 1:1 copies of 翰林 學用 pages (verified page-by-page, see verify_vol.py),
so we parse 學用 PDFs for the printed numbering, then match each 教用 item by stem text.

Output: data/book_align.json  { "<sem>|<ch>|<key>": {label, page(book printed page), vpage} }
"""
import pymupdf, re, json, difflib, collections
from parse import build, SEMS
from align import N, strip_marker, region_text

vmap = json.load(open('/home/claude/work/data/vol_map_xueyong.json'))
# 學用 page -> (vol, volume pdf page)
src2vol = {}
for v, rows in vmap.items():
    for vp, src, sc in rows:
        if src:
            src2vol[(src[0], src[1])] = (int(v), vp)


def items_of(doc, chs, sem):
    out = collections.OrderedDict()
    for c in chs:
        L = []
        for it in c['items']:
            if it['type'] == 'passage':
                continue
            if it['type'] == 'q':
                reg = [tuple(it['stem'][0]), tuple(it['jx'][0]) if it.get('jx') else tuple(it['stem'][1])]
                L.append({'key': str(it['num']), 'kind': 'q', 'label': str(it['num']), 'sig': strip_marker(region_text(doc, reg), 'q'), 'pg': it['stem'][0][0]})
            else:
                reg = [tuple(it['stem'][0]), tuple(it['subs'][0]['stem'][0])]
                L.append({'key': f"{it['num']}|g", 'kind': 'group', 'label': str(it['num']), 'sig': strip_marker(region_text(doc, reg), 'group'), 'pg': it['stem'][0][0]})
                for s in it['subs']:
                    reg = [tuple(s['stem'][0]), tuple(s['jx'][0]) if s.get('jx') else tuple(s['stem'][1])]
                    L.append({'key': f"{it['num']}|g|{s['num']}", 'kind': 'sub', 'label': f"{it['num']}({s['num']})", 'sig': strip_marker(region_text(doc, reg), 'sub'), 'pg': s['stem'][0][0]})
        out[c['ch']] = L
    return out


def sim(a, b):
    a, b = a[:40], b[:40]
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def main():
    result = {}
    report = []
    for sem in SEMS:
        jd, jchs, _ = build(sem, '教用')
        xd, xchs, xflags = build(sem, '學用')
        J = items_of(jd, jchs, sem)
        X = items_of(xd, xchs, sem)
        xfull = [N(p.get_text()) for p in xd]
        for ch, jl in J.items():
            xl = X.get(ch, [])
            used = set()
            for j in jl:
                best, bs = None, 0.0
                # same kind, prefer same label
                for i, x in enumerate(xl):
                    if i in used or x['kind'] != j['kind']:
                        continue
                    s = sim(j['sig'], x['sig']) + (0.05 if x['label'] == j['label'] else 0)
                    if s > bs:
                        bs, best = s, i
                key = f"{sem}|{ch}|{j['key']}"
                if best is not None and bs >= 0.65:
                    used.add(best)
                    x = xl[best]
                    vol, vp = src2vol.get((sem, x['pg'] + 1), (None, None))
                    result[key] = {'label': x['label'], 'vol': vol, 'vpage': vp, 'page': (vp - 4) if vp else None, 'score': round(bs, 2)}
                else:
                    # fallback: locate the stem text in 學用 pages, read the printed number right before it
                    sig = j['sig'][:12]
                    hit = None
                    for pi, t in enumerate(xfull):
                        k = t.find(sig) if len(sig) >= 8 else -1
                        if k >= 0:
                            pre = t[max(0, k - 12):k]
                            m = re.search(r'(\d{1,3})[.．、]?$', pre) if j['kind'] != 'sub' else re.search(r'[（(](\d)[)）]\.?$', pre)
                            hit = (pi, m.group(1) if m else None)
                            break
                    if hit:
                        vol, vp = src2vol.get((sem, hit[0] + 1), (None, None))
                        lab = hit[1]
                        result[key] = {'label': lab, 'vol': vol, 'vpage': vp, 'page': (vp - 4) if vp else None, 'score': 'text', 'printed_typo': True}
                    else:
                        result[key] = {'label': None}
                        report.append(f'{key} 題本中找不到')
            for i, x in enumerate(xl):
                if i not in used:
                    report.append(f"{sem} ch{ch} 題本有、教用無: {x['label']} sig={x['sig'][:20]}")
    json.dump(result, open('/home/claude/work/data/book_align.json', 'w'), ensure_ascii=False, indent=0)
    return result, report


if __name__ == '__main__':
    res, rep = main()
    print('items', len(res))
    for r in rep:
        print('  !', r)
    diff = []
    for k, r in res.items():
        parts = k.split('|')
        exp = parts[2] if len(parts) <= 4 else f"{parts[2]}({parts[4]})"
        if r.get('label') != exp:
            diff.append((k, r))
    print('題號不同:', len(diff))
    for d in diff:
        print('  ', d)
