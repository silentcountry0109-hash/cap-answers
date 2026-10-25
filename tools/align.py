"""Align every 教用 item (question / 題組 / 小題) to the printed book (三冊題本 PDF).

The printed book was built from 翰林 學用 pages; its numbering is what students see.
For each 教用 item we locate its stem text in the book and read the printed number.
Output: data/book_align.json  { "<sem>|<ch>|<num>[|g|<sub>]": {book, page, pos} }
"""
import pymupdf, re, json, bisect, collections, sys
from parse import build, SEMS

VOL = {1: '/mnt/user-data/uploads/歷屆會考題目/第一冊_國中自然_生物篇.pdf',
       2: '/mnt/user-data/uploads/歷屆會考題目/第二冊_國中自然_理化上篇.pdf',
       3: '/mnt/user-data/uploads/歷屆會考題目/第三冊_國中自然_理化下與地科篇.pdf'}
VSEM = {1: ['1上', '1下'], 2: ['2上', '2下'], 3: ['3上', '3下']}
N = lambda t: re.sub(r'\s+', '', t)
GENERIC = re.compile(r'^(請(在)?閱讀下列(敘述|短文|文章|資料)?後?，?回答(第)?(\(\d\)|（\d）)?(～(\(\d\)|（\d）))?\s*(小)?題(目)?[。：:]?|請(在)?閱讀下列(敘述|短文|文章)?後?，?回答問題[。：:]?)')
SRC = '/home/claude/work/src'


def region_text(doc, reg):
    (p0, y0), (p1, y1) = reg
    out = ''
    for pg in range(p0, p1 + 1):
        page = doc[pg]
        top = y0 - 1 if pg == p0 else 40
        bot = y1 - 1 if pg == p1 else 808
        if bot <= top:
            continue
        out += page.get_text(clip=pymupdf.Rect(0, top, page.rect.width, bot))
    return N(out)


def strip_marker(t, kind):
    t = re.sub(r'^[（(][^）)]{0,6}[）)]', '', t)
    if kind == 'sub':
        t = re.sub(r'^[（(]\d+[)）]\.?', '', t)
    else:
        t = re.sub(r'^\d{1,3}[.．、]?', '', t)
    if kind == 'group':
        t = GENERIC.sub('', t)
    t = re.sub(r'^【[^】]{0,12}】', '', t)
    return t


def main():
    result = {}
    problems = []
    for v, path in VOL.items():
        vd = pymupdf.open(path)
        pages = [N(p.get_text()) for p in vd]
        starts = []; full = ''
        for t in pages:
            starts.append(len(full)); full += t
        page_of = lambda pos: bisect.bisect_right(starts, pos)  # 1-based pdf page
        # chapter windows in book: positions of "第N章歷屆" headings
        heads = [starts[page_of(m.start()) - 1] for m in re.finditer(r'第(\d+|[一二三四五六七八九十])章歷屆大考(考|試)題', full)]
        heads.append(len(full))
        hi = 0
        for sem in VSEM[v]:
            doc, chs, _ = build(sem)
            for c in chs:
                w0, w1 = heads[hi], heads[hi + 1]; hi += 1
                win = full[w0:w1]
                items = []
                for it in c['items']:
                    if it['type'] == 'q':
                        items.append(('q', it, None))
                    else:
                        items.append(('group', it, None))
                        for s in it['subs']:
                            items.append(('sub', it, s))
                cursor = 0
                for kind, it, s in items:
                    obj = s if s else it
                    key = f"{sem}|{c['ch']}|{it['num']}" + (f"|g|{s['num']}" if s else ('|g' if kind == 'group' else ''))
                    if kind == 'group' and it.get('subs'):
                        reg = [tuple(it['stem'][0]), tuple(it['subs'][0]['stem'][0])]
                    else:
                        reg = [tuple(obj['stem'][0]), tuple(obj['jx'][0]) if obj.get('jx') else tuple(obj['stem'][1])]
                    raw = region_text(doc, reg)
                    sig = strip_marker(raw, kind)
                    found = None
                    for L in (24, 16, 10, 7):
                        if len(sig) < L:
                            continue
                        needle = sig[:L]
                        occ = [m.start() for m in re.finditer(re.escape(needle), win)]
                        if not occ:
                            continue
                        # prefer first occurrence at/after cursor, else nearest
                        after = [o for o in occ if o >= cursor - 50]
                        found = after[0] if after else occ[0]
                        break
                    if found is None:
                        problems.append((key, 'not found', sig[:20]))
                        result[key] = {'book': None}
                        continue
                    pre = win[max(0, found - 40):found]
                    num = None
                    if kind == 'sub':
                        m = re.search(r'[（(](\d{1,2})[)）]\.?$', pre)
                        num = m.group(1) if m else None
                    elif kind == 'q':
                        m = re.search(r'(\d{1,3})[.．、]?$', re.sub(r'【[^】]*】$', '', pre))
                        num = m.group(1) if m else None
                    else:
                        ms = list(re.finditer(r'(?<![\d.])(\d{1,3})[.．]', pre))
                        num = ms[-1].group(1) if ms else None
                    pos = w0 + found
                    result[key] = {'book': num, 'page': page_of(pos), 'pos': pos, 'vol': v}
                    cursor = found
    json.dump(result, open('/home/claude/work/data/book_align.json', 'w'), ensure_ascii=False, indent=0)
    return result, problems


if __name__ == '__main__':
    res, problems = main()
    print('items', len(res), 'problems', len(problems))
    for p in problems:
        print('  ', p)
    # numbering differences
    diff = []
    for k, r in res.items():
        parts = k.split('|')
        exp = parts[4] if len(parts) == 5 else parts[2]
        if r.get('book') != exp:
            diff.append((k, r.get('book'), r.get('page')))
    print('numbering differences:', len(diff))
    for d in diff:
        print('  ', d)
