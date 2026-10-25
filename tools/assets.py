"""Region analysis + crop rendering with own/foreign content separation."""
import pymupdf, re, io
from PIL import Image, ImageDraw
from parse import FOOTER_Y, PAGE_BOTTOM, is_pageno
from content import render_text, PUA, SAFE_FONT_BAD

TOP = 40
ZOOM = 2.5
PAD = 3


def colored(c):
    r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
    return max(r, g, b) - min(r, g, b) > 90


class Page:
    def __init__(self, page):
        self.page = page
        self.lines = []
        for b in page.get_text('dict')['blocks']:
            if b['type'] != 0:
                continue
            for l in b['lines']:
                t = ''.join(s['text'] for s in l['spans'])
                if not t.strip():
                    continue
                if is_pageno(t, l['bbox']):
                    continue
                vis = [s for s in l['spans'] if s['text'].strip()]
                l['_rect'] = pymupdf.Rect(l['bbox'])
                n = sum(len(s['text'].strip()) for s in vis) or 1
                l['_color_ratio'] = sum(len(s['text'].strip()) for s in vis if colored(s['color'])) / n
                l['_white'] = all(s['color'] == 0xffffff for s in vis)
                self.lines.append(l)
        self.graphics = []  # (rect, kind, obj)
        for i in page.get_image_info():
            r = pymupdf.Rect(i['bbox'])
            if r.width > 2 and r.height > 2:
                self.graphics.append((r, 'image', i))
        for d in page.get_drawings():
            r = pymupdf.Rect(d['rect'])
            if r.width < 1.2 and r.height < 1.2:
                continue
            if d.get('fill') == (1.0, 1.0, 1.0) and not d.get('color'):
                continue  # white fills (masks)
            self.graphics.append((r, 'draw', d))


class Doc:
    def __init__(self, path):
        self.doc = pymupdf.open(path)
        self._p = {}

    def page(self, i):
        if i not in self._p:
            self._p[i] = Page(self.doc[i])
        return self._p[i]


def bands(reg):
    (p0, y0), (p1, y1) = reg
    out = []
    for pg in range(p0, p1 + 1):
        top = y0 - 1.0 if pg == p0 else TOP
        bot = y1 - 1.0 if pg == p1 else PAGE_BOTTOM
        if bot - top > 2:
            out.append((pg, top, bot))
    return out


def is_underline(g, spans):
    """thin horizontal rule directly under some text and not a fraction bar"""
    if g.height > 1.8 or g.width < 2:
        return False
    above = [s for s in spans if s['bbox'][0] < g.x1 - 1 and s['bbox'][2] > g.x0 + 1 and -2.5 <= g.y0 - s['bbox'][3] <= 3.0]
    if not above:
        return False
    below = [s for s in spans if -1 <= s['bbox'][1] - g.y1 <= 4 and s['bbox'][0] >= g.x0 - 3 and s['bbox'][2] <= g.x1 + 3 and s['text'].strip()]
    return not below


def analyse(D, reg, kind):
    """kind: 'jx' (解析) or 'stem' (題目/題組/文章).
    Returns dict with segs=[{pg, crop:Rect, own_lines, whiten:[Rect]}], mode, reasons, html"""
    segs = []
    reasons = set()
    all_own_lines = []
    for pg, top, bot in bands(reg):
        P = D.page(pg)
        inband = [l for l in P.lines if top <= (l['bbox'][1] + l['bbox'][3]) / 2 < bot and l['bbox'][1] >= top - 2]
        if kind == 'jx':
            own_lines = [l for l in inband if l['_color_ratio'] > 0.5]
        else:
            own_lines = [l for l in inband if not l['_white']]
        # graphics ownership
        own_g, foreign_g = [], []
        for r, gk, obj in P.graphics:
            if r.y1 < top - 1 or r.y0 > bot + 1:
                continue
            inside = max(0.0, min(r.y1, bot) - max(r.y0, top))
            frac = inside / max(r.height, 0.5)
            if kind == 'jx':
                ok = frac >= 0.6 and r.y1 <= bot + 6
            else:
                ok = frac >= 0.5
            (own_g if ok else foreign_g).append((r, gk, obj))
        if kind == 'jx':
            # thin rules are own only when attached to own text (underline / fraction bar)
            ospans = [sp for l in own_lines for sp in l['spans'] if sp['text'].strip()]
            keep = []
            for g in own_g:
                r = g[0]
                if r.height < 1.8 or r.width < 1.8:
                    near = [sp for sp in ospans if sp['bbox'][0] < r.x1 + 1 and sp['bbox'][2] > r.x0 - 1 and (-3 <= r.y0 - sp['bbox'][3] <= 4 or -1 <= sp['bbox'][1] - r.y1 <= 4)]
                    if not near:
                        foreign_g.append(g); continue
                keep.append(g)
            own_g = keep
            # black lines inside an own graphic (figure labels of 解析 figures) are own too
            for l in inband:
                if l in own_lines or l['_white']:
                    continue
                if any(l['_rect'].intersects(r) and (l['_rect'] & r).get_area() > 0.6 * l['_rect'].get_area() for r, gk, o in own_g if r.width > 20 and r.height > 12):
                    own_lines.append(l)
        if not own_lines and not own_g:
            continue
        crop = pymupdf.Rect()
        for l in own_lines:
            crop |= l['_rect']
        for r, gk, o in own_g:
            crop |= r
        crop = pymupdf.Rect(crop.x0 - PAD, crop.y0 - PAD, crop.x1 + PAD, crop.y1 + PAD) & P.page.rect
        own_ids = set(id(l) for l in own_lines)
        whiten = []
        for l in P.lines:
            if id(l) in own_ids:
                continue
            if l['_rect'].intersects(crop):
                whiten.append(l['_rect'])
        for r, gk, o in foreign_g:
            if r.intersects(crop):
                whiten.append(r)
        # reasons (text-mode eligibility) — only for 解析
        if kind == 'jx':
            spans = [s for l in own_lines for s in l['spans'] if s['text'].strip()]
            for r, gk, o in own_g:
                if gk == 'image':
                    reasons.add('image')
                elif is_underline(r, spans):
                    continue
                else:
                    reasons.add('drawing')
        for l in own_lines:
            l['_pg'] = pg
        all_own_lines.extend(own_lines)
        keep_rects = [l['_rect'] for l in own_lines]
        segs.append({'pg': pg, 'crop': crop, 'whiten': whiten, 'keep': keep_rects})
    res = {'segs': segs, 'kind': kind}
    if kind == 'jx':
        txt = ''.join(s['text'] for l in all_own_lines for s in l['spans'])
        if PUA.search(txt):
            reasons.add('pua')
        for l in all_own_lines:
            for s in l['spans']:
                if s['text'].strip() and SAFE_FONT_BAD.search(s['font']):
                    reasons.add('symfont')
        rows = sorted(all_own_lines, key=lambda l: (l['_pg'], l['bbox'][1], l['bbox'][0]))
        # visual rows (same page & baseline)
        vrows = []
        for l in rows:
            if vrows and vrows[-1][0]['_pg'] == l['_pg'] and abs(vrows[-1][0]['bbox'][1] - l['bbox'][1]) < 2.5:
                vrows[-1].append(l)
            else:
                vrows.append([l])
        xs = sorted(min(x['bbox'][0] for x in vr) for vr in vrows[1:])
        cont_x = xs[len(xs) // 2] if xs else None
        for vr in vrows:
            sp = sorted([x for l in vr for x in l['spans'] if x['text'].strip()], key=lambda x: x['bbox'][0])
            if not sp:
                continue
            fs = max(x['size'] for x in sp)
            for a_, b_ in zip(sp, sp[1:]):
                if b_['bbox'][0] - a_['bbox'][2] > 2.2 * fs:
                    reasons.add('tabular'); break
            x0 = sp[0]['bbox'][0]
            if cont_x is not None and vr is not vrows[0] and x0 > cont_x + 2.5 * fs:
                reasons.add('indent')
            # text with long internal runs of spaces (tab alignment)
            if re.search(r'\S\s{4,}\S', ''.join(x['text'] for l in vr for x in l['spans'])):
                reasons.add('tabular')
        for i in range(len(rows) - 1):
            a, b = rows[i], rows[i + 1]
            if a['_pg'] == b['_pg'] and b['bbox'][1] < a['bbox'][3] - 2 and abs(b['bbox'][1] - a['bbox'][1]) > 2.5:
                reasons.add('stack'); break
        res['reasons'] = sorted(reasons)
        res['mode'] = 'image' if reasons else 'text'
        res['plain'] = re.sub(r'\s+', '', txt)
        if res['mode'] == 'text':
            res['html'] = render_text(all_own_lines)
    return res


def render(D, res, zoom=ZOOM, gap=14):
    ims = []
    for s in res['segs']:
        page = D.doc[s['pg']]
        crop = s['crop']
        pix = page.get_pixmap(clip=crop, matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        if s['whiten']:
            orig = im.copy()
            dr = ImageDraw.Draw(im)
            for r in s['whiten']:
                rr = r & crop
                if rr.is_empty:
                    continue
                dr.rectangle([(rr.x0 - crop.x0) * zoom - 1, (rr.y0 - crop.y0) * zoom - 1, (rr.x1 - crop.x0) * zoom + 1, (rr.y1 - crop.y0) * zoom + 1], fill=(255, 255, 255))
            # paste back own content areas that a foreign rect may have covered
            for r in s.get('keep', []):
                rr = r & crop
                if rr.is_empty:
                    continue
                if not any(rr.intersects(w) for w in s['whiten']):
                    continue
                box = (max(0, int((rr.x0 - crop.x0) * zoom) - 1), max(0, int((rr.y0 - crop.y0) * zoom) - 1),
                       min(im.width, int((rr.x1 - crop.x0) * zoom) + 2), min(im.height, int((rr.y1 - crop.y0) * zoom) + 2))
                if box[2] > box[0] and box[3] > box[1]:
                    im.paste(orig.crop(box), box[:2])
        if s.get('erase'):
            dr = ImageDraw.Draw(im)
            for r in s['erase']:
                rr = r & crop
                if not rr.is_empty:
                    dr.rectangle([(rr.x0 - crop.x0) * zoom - 1, (rr.y0 - crop.y0) * zoom - 1, (rr.x1 - crop.x0) * zoom + 1, (rr.y1 - crop.y0) * zoom + 1], fill=(255, 255, 255))
        ims.append(im)
    if not ims:
        return None
    W = max(i.width for i in ims)
    H = sum(i.height for i in ims) + gap * (len(ims) - 1)
    out = Image.new('RGB', (W, H), (255, 255, 255))
    y = 0
    for i in ims:
        out.paste(i, (0, y)); y += i.height + gap
    return out


def answer_spans(D, res, start):
    """rects of the answer letter(s) inside the leading （ X ） of the marker line (char-level)"""
    pg0, y0 = start
    page = D.doc[pg0]
    out = []
    raw = page.get_text('rawdict', clip=pymupdf.Rect(0, y0 - 3, page.rect.width, y0 + 16))
    for b in raw['blocks']:
        if b.get('type') != 0:
            continue
        for l in b['lines']:
            if abs(l['bbox'][1] - y0) > 3:
                continue
            chars = [c for s in l['spans'] for c in s['chars']]
            txt = ''.join(c['c'] for c in chars)
            m = re.match(r'^\s*[（(]', txt)
            if not m:
                continue
            for c in chars[m.end():]:
                if c['c'] in '）)':
                    break
                if c['c'] in 'ABCDEＡＢＣＤＥ':
                    out.append(pymupdf.Rect(c['bbox']))
            break
    for s in res['segs']:
        if s['pg'] == pg0:
            s['erase'] = out
    return out
