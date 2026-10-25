"""Extract 解析 content per item: decide text (reflowable HTML) vs image crop."""
import pymupdf, re, html, collections, json, sys
from parse import build, SEMS, FOOTER_Y, PAGE_BOTTOM, is_pageno

TOP = 40
PUA = re.compile(r'[-]')
SAFE_FONT_BAD = re.compile(r'Symbol|Wingdings|MT ?Extra|Math', re.I)


def segs_of(reg, npages):
    (p0, y0), (p1, y1) = reg
    out = []
    for pg in range(p0, p1 + 1):
        top = y0 - 1.5 if pg == p0 else TOP
        bot = y1 - 1.5 if pg == p1 else PAGE_BOTTOM
        if bot - top > 2:
            out.append((pg, top, bot))
    return out


class PageCache:
    def __init__(self, doc):
        self.doc = doc
        self.c = {}

    def get(self, pg):
        if pg not in self.c:
            p = self.doc[pg]
            lines = []
            for b in p.get_text('dict', flags=pymupdf.TEXT_PRESERVE_WHITESPACE)['blocks']:
                if b['type'] != 0:
                    continue
                for l in b['lines']:
                    t = ''.join(s['text'] for s in l['spans'])
                    if not t.strip():
                        continue
                    if is_pageno(t, l['bbox']):
                        continue
                    lines.append(l)
            imgs = [pymupdf.Rect(i['bbox']) for i in p.get_image_info()]
            drs = []
            for d in p.get_drawings():
                r = d['rect']
                drs.append((pymupdf.Rect(r), d))
            self.c[pg] = (p, lines, imgs, drs)
        return self.c[pg]


def lines_in(cache, seg):
    pg, top, bot = seg
    p, lines, imgs, drs = cache.get(pg)
    out = []
    for l in lines:
        cy = (l['bbox'][1] + l['bbox'][3]) / 2
        if top <= l['bbox'][1] + 0.5 and cy < bot:
            out.append(l)
    return out


def content_rect(cache, seg, lines):
    """Bounding rect of everything (text, images, drawings) inside the segment band."""
    pg, top, bot = seg
    p, _, imgs, drs = cache.get(pg)
    band = pymupdf.Rect(30, top, p.rect.width - 30, bot)
    r = pymupdf.Rect()
    for l in lines:
        r |= pymupdf.Rect(l['bbox'])
    for im in imgs:
        if im.intersects(band) and (im & band).height > 3:
            r |= (im & band)
    for dr, d in drs:
        if dr.intersects(band) and (dr & band).height >= 0 and (dr & band).width > 0:
            r |= (dr & band)
    return r


def analyse_region(cache, reg, npages):
    """Return dict(mode='text'|'image', html=..., segs=[(pg, rect)], reasons=[...])."""
    reasons = []
    segs = segs_of(reg, npages)
    rows_all = []
    crop = []
    for seg in segs:
        pg, top, bot = seg
        p, _, imgs, drs = cache.get(pg)
        ls = lines_in(cache, seg)
        cr = content_rect(cache, seg, ls)
        if not cr.is_empty and cr.height > 2:
            crop.append((pg, [round(cr.x0, 1), round(max(cr.y0, top), 1), round(cr.x1, 1), round(min(cr.y1, bot) + 1, 1)]))
        band = pymupdf.Rect(30, top, p.rect.width - 30, bot)
        # images
        for im in imgs:
            if im.intersects(band) and (im & band).height > 3 and (im & band).width > 3:
                reasons.append('image')
        # text spans for underline / fraction tests
        spans = [s for l in ls for s in l['spans'] if s['text'].strip()]
        for dr, d in drs:
            if not dr.intersects(band):
                continue
            inter = dr & band
            if inter.width < 1.5 and inter.height < 1.5:
                continue
            horiz = dr.height <= 1.6 and dr.width >= 2
            if horiz:
                above = [s for s in spans if s['bbox'][0] < dr.x1 - 1 and s['bbox'][2] > dr.x0 + 1 and 0 <= dr.y0 - s['bbox'][3] <= 4.5]
                below = [s for s in spans if s['bbox'][0] < dr.x1 - 1 and s['bbox'][2] > dr.x0 + 1 and -1 <= s['bbox'][1] - dr.y1 <= 3.5]
                inside = [s for s in spans if s['bbox'][1] - 1 <= dr.y0 <= s['bbox'][3] - 1 and s['bbox'][0] < dr.x1 and s['bbox'][2] > dr.x0]
                if above and not below:
                    continue  # underline (專名號)
                if not above and not below and inside:
                    continue  # strike / table rule inside text? treat as decoration
                reasons.append('rule')
            else:
                reasons.append('drawing')
        for l in ls:
            l['_pg'] = pg
        rows_all.extend(ls)
    # text checks
    txt = ''.join(s['text'] for l in rows_all for s in l['spans'])
    if PUA.search(txt):
        reasons.append('pua')
    for l in rows_all:
        for s in l['spans']:
            if s['text'].strip() and SAFE_FONT_BAD.search(s['font']):
                reasons.append('symfont:' + s['font'])
    # vertical structure: overlapping rows with different baselines
    rows = sorted(rows_all, key=lambda l: (l['_pg'], l['bbox'][1], l['bbox'][0]))
    for i in range(len(rows) - 1):
        if rows[i]['_pg'] != rows[i + 1]['_pg']:
            continue
        a, b = rows[i], rows[i + 1]
        if b['bbox'][1] < a['bbox'][3] - 2 and abs(b['bbox'][1] - a['bbox'][1]) > 2.5:
            reasons.append('stack')
            break
    reasons = sorted(set(reasons))
    mode = 'image' if reasons else 'text'
    return {'mode': mode, 'reasons': reasons, 'crop': crop, 'lines': rows_all}


# ---------- text rendering ----------
UNIT_END = re.compile(r'(?:(?<![A-Za-z])(?:cm|mm|km|dm|m|s)|/(?:cm|m|s))$')


def span_html(s, base, main_size, prev_text=''):
    raw = s['text']
    t = html.escape(raw)
    if not t:
        return ''
    size = s['size']
    oy = s['origin'][1]
    core = raw.strip()
    if size < main_size * 0.85 and core:
        if oy > base + 0.8:
            return f'<sub>{t}</sub>'
        if oy < base - 0.8:
            return f'<sup>{t}</sup>'
        # same reported baseline: decide by content
        p = prev_text.rstrip()
        if re.fullmatch(r'[0-9]*[+＋\-－−]', core):
            return f'<sup>{html.escape(core)}</sup>'
        if re.search(r'10$', p) and re.fullmatch(r'[－\-−]?\d+', core):
            return f'<sup>{html.escape(core)}</sup>'
        if UNIT_END.search(p) and core in ('2', '3', '－1', '-1', '－2', '-2'):
            return f'<sup>{html.escape(core)}</sup>'
        lead = ' ' if raw[:1] == ' ' and not p.endswith(' ') else ''
        return f'<sub>{html.escape(core)}</sub>' if not lead else f'<sub>{html.escape(core)}</sub>'
    return t


def is_cjk(ch):
    return '⺀' <= ch <= '鿿' or '＀' <= ch <= '￯' or '　' <= ch <= '〿'


def render_text(lines, label_re=r'^\s*解\s*析\s*[：:]?\s*'):
    """Group lines into visual rows, join rows into paragraphs, output HTML."""
    rows = []
    for l in sorted(lines, key=lambda l: (l.get('_pg', 0), round(l['bbox'][1] / 2), l['bbox'][0])):
        if rows and rows[-1][0].get('_pg', 0) == l.get('_pg', 0) and abs(rows[-1][0]['bbox'][1] - l['bbox'][1]) < 2.5:
            rows[-1].append(l)
        else:
            rows.append([l])
    out_rows = []
    for row in rows:
        row.sort(key=lambda l: l['bbox'][0])
        spans = [s for l in row for s in l['spans']]
        if not spans:
            continue
        main = max(spans, key=lambda s: len(s['text'].strip()) * s['size'])
        main_size, base = main['size'], main['origin'][1]
        parts = []; prev = ''
        for sp in spans:
            parts.append(span_html(sp, base, main_size, prev))
            prev += sp['text']
        h = ''.join(parts)
        # right edge of visible text
        vis = [s for s in spans if s['text'].strip()]
        x1 = max(s['bbox'][2] for s in vis) if vis else row[-1]['bbox'][2]
        out_rows.append({'x0': row[0]['bbox'][0], 'x1': x1, 'html': h, 'size': main_size})
    if not out_rows:
        return ''
    out_rows[0]['html'] = re.sub(label_re, '', out_rows[0]['html'])
    right = max(r['x1'] for r in out_rows)
    paras = []
    cur = ''
    ENUM = re.compile(r'^(\([A-E]\)|（[A-E]）|\(\d\)|（\d）|[①-⑳]|[甲乙丙丁戊]：|\d+\.(?!\d))')
    for i, r in enumerate(out_rows):
        hs = r['html'].strip()
        if not hs:
            continue
        new_para = False
        if i > 0 and cur:
            prev = out_rows[i - 1]
            ptxt = re.sub(r'<[^>]+>', '', cur).rstrip()
            hard_break = prev['x1'] < right - max(18, prev['size'] * 1.6)
            if hard_break:
                new_para = True
            elif ENUM.match(hs) and (ptxt.endswith(('。', '：', '；', ':', ';')) or abs(r['x0'] - prev['x0']) > 3):
                new_para = True
        if new_para:
            paras.append(cur); cur = hs
        else:
            if cur:
                a, b = re.sub(r'<[^>]+>', '', cur)[-1:], re.sub(r'<[^>]+>', '', hs)[:1]
                if a and b and not is_cjk(a) and not is_cjk(b) and a.isalnum() and b.isalnum():
                    cur += ' '
            cur += hs
    if cur:
        paras.append(cur)
    CIRC = '①②③④⑤⑥⑦⑧⑨⑩'
    def circ(m):
        n = int(m.group(1))
        return CIRC[n - 1] if 1 <= n <= 10 else m.group(0)
    out = ''
    for p in paras:
        p = re.sub(r'  +', ' ', p).strip()
        p = re.sub(r'○\s*<su[bp]>(\d{1,2})</su[bp]>', circ, p)
        p = re.sub(r'○(\d)(?!\d)', circ, p)
        out += f'<p>{p}</p>'
    return out


if __name__ == '__main__':
    stats = collections.Counter(); rs = collections.Counter(); per = collections.defaultdict(collections.Counter)
    samples = collections.defaultdict(list)
    for sem in SEMS:
        doc, chs, _ = build(sem)
        cache = PageCache(doc)
        for c in chs:
            for it in c['items']:
                objs = [it] if it['type'] == 'q' else it['subs']
                for o in objs:
                    if not o.get('jx'):
                        continue
                    a = analyse_region(cache, o['jx'], len(doc))
                    stats[a['mode']] += 1; per[sem][a['mode']] += 1
                    for r in a['reasons']:
                        rs[r.split(':')[0]] += 1
                        if len(samples[r.split(':')[0]]) < 6:
                            samples[r.split(':')[0]].append(f"{sem} ch{c['ch']} {it['num']} p{o['jx'][0][0]+1}")
    print(stats, dict(per))
    print(rs)
    for k, v in samples.items():
        print(k, v)
