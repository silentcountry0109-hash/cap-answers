"""Parse 翰林 歷屆大考考題 教用合檔 PDFs into question / answer / 解析 regions.

Output: data/<sem>.json  — list of chapters, each with items (questions / groups),
every item carrying page regions for the stem and for the 解析.
"""
import pymupdf, re, json, sys, collections, os

SRC = os.environ.get('CAP_SRC', '/home/claude/work/src')
OUT = '/home/claude/work/data'
SEMS = ['1上', '1下', '2上', '2下', '3上', '3下']
QX = {'1上': 90, '1下': 57, '2上': 57, '2下': 57, '3上': 57, '3下': 71}
FOOTER_Y = 772
PAGE_BOTTOM = 808


def is_pageno(t, bbox):
    return bbox[1] >= FOOTER_Y and re.fullmatch(r'\s*\d+\s*', t) is not None and abs((bbox[0] + bbox[2]) / 2 - 297.6) < 40
TOP_Y = 40

FW = str.maketrans('ＡＢＣＤＥ０１２３４５６７８９', 'ABCDE0123456789')
CN = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}

RE_CH = re.compile(r'^第\s*([一二三四五六七八九十\d]+)\s*章.*歷屆')
RE_Q = re.compile(r'^[（(]\s*([A-EＡ-Ｅ]{1,4})?\s*[）)]\s*(\d{1,3})\s*[.．、]?')
RE_SUB = re.compile(r'^[（(]\s*([A-EＡ-Ｅ]{1,4})?\s*[）)]\s*[（(]\s*(\d{1,2})\s*[)）]')
RE_GRP = re.compile(r'^(\d{1,3})\s*[.．]\s*(.*)')
RE_JX = re.compile(r'^解\s*析')


def page_lines(page):
    out = []
    for b in page.get_text('dict')['blocks']:
        if b['type'] != 0:
            continue
        for l in b['lines']:
            t = ''.join(s['text'] for s in l['spans'])
            if not t.strip():
                continue
            x0, y0, x1, y1 = l['bbox']
            if is_pageno(t, l['bbox']):
                continue
            out.append({'t': t, 'bbox': (x0, y0, x1, y1), 'spans': l['spans']})
    out.sort(key=lambda L: (round(L['bbox'][1] / 3), L['bbox'][0]))
    return out


def candidates(L, qx, allow_empty=False):
    """Return possible marker interpretations for a line (validated later by sequence)."""
    t = L['t'].strip()
    x0 = L['bbox'][0]
    if RE_CH.match(t):
        g = RE_CH.match(t).group(1)
        return ('CH', int(g) if g.isdigit() else CN.get(g, 0))
    if RE_JX.match(t) and x0 < 230:
        return ('JX',)
    if x0 < qx + 20 and re.match(r'^請(在)?閱讀下列.{0,8}回答', t):
        return ('PSG',)
    if x0 < qx + 60:
        m = RE_SUB.match(t)
        if m:
            return ('SUB', (m.group(1) or '').translate(FW), int(m.group(2)))
        m = RE_Q.match(t)
        if m and (m.group(1) or (allow_empty and re.match(r'^[（(]\s*[）)]', t))):
            par = t[:m.end(1)+3]
            marker_like = ('（' in par) or re.match(r'^[（(]\s+[A-EＡ-Ｅ]', t) or x0 < qx + 30
            if marker_like:
                return ('Q', (m.group(1) or '').translate(FW), int(m.group(2)))
        m = RE_GRP.match(t)
        if m:
            return ('GRP', int(m.group(1)))
    return None


def parse(sem, kind='教用'):
    doc = pymupdf.open(f'{SRC}/{sem}_{kind}.pdf')
    qx = QX[sem]
    raw = []
    for pi, page in enumerate(doc):
        for L in page_lines(page):
            c = candidates(L, qx, allow_empty=(kind != '教用'))
            if c:
                raw.append({'k': c[0], 'v': list(c[1:]), 'pg': pi, 'y': L['bbox'][1], 'x': L['bbox'][0], 't': L['t'].strip()})
    # sequence validation
    ev = []
    flags = []
    ch = None; nxt = 1; last_main = None; in_group = False; last_sub = 0
    for i, e in enumerate(raw):
        k = e['k']
        if k == 'CH':
            ch = e['v'][0]; nxt = 1; last_main = None; in_group = False; last_sub = 0
            ev.append(e); continue
        if ch is None:
            continue
        if k == 'JX':
            ev.append(e); continue
        if k == 'PSG':
            e['ch'] = ch
            ev.append(e); in_group = False; last_sub = 0
            continue
        if k in ('Q', 'GRP'):
            n = e['v'][-1] if k == 'Q' else e['v'][0]
            ok = None
            if n == nxt:
                ok = 'seq'
            elif n == nxt - 1 and last_main == n and k == 'Q' and re.search(r'\d\s*[.．]\s*[\u4e00-\u9fff「]', e['t'][:16]):
                ok = 'dup'
            elif n == nxt + 1 and k == 'Q':
                ok = 'skip'
            if not ok:
                continue
            if k == 'GRP':
                # must be followed by a SUB marker before any Q / JX
                j = i + 1
                while j < len(raw):
                    r = raw[j]
                    if r['k'] in ('SUB', 'JX', 'CH'):
                        break
                    if r['k'] == 'Q' and r['v'][1] == n + 1:
                        break
                    j += 1
                if j >= len(raw) or raw[j]['k'] != 'SUB':
                    continue
            if ok == 'dup':
                flags.append(f'ch{ch}: 題號 {n} 重複（原書印刷如此）p{e["pg"]+1}')
            if ok == 'skip':
                flags.append(f'ch{ch}: 題號跳號 {nxt} 缺 p{e["pg"]+1}')
            e['ch'] = ch
            ev.append(e)
            last_main = n; nxt = n + 1
            in_group = (k == 'GRP'); last_sub = 0
            continue
        if k == 'SUB':
            s = e['v'][1]
            if not e['v'][0] and kind == '教用':
                continue
            if s == last_sub + 1 and (in_group or s == 1):
                if not in_group:
                    # implicit group: the SUB follows a regular question number
                    flags.append(f'ch{ch}: 題組 {nxt} 未偵測到題幹行，自動補 p{e["pg"]+1}')
                    ev.append({'k': 'GRP', 'v': [nxt], 'pg': e['pg'], 'y': e['y'], 'x': e['x'], 't': '(implicit)', 'ch': ch, 'implicit': True})
                    last_main = nxt; nxt += 1; in_group = True
                last_sub = s
                e['ch'] = ch
                ev.append(e)
            continue
    return doc, ev, flags


def build(sem, kind='教用'):
    doc, ev, flags = parse(sem, kind)
    chapters = []
    cur = None
    # attach end positions: each event ends where the next event (any kind) starts
    for i, e in enumerate(ev):
        nx = ev[i + 1] if i + 1 < len(ev) else {'pg': len(doc) - 1, 'y': PAGE_BOTTOM}
        e['end'] = (nx['pg'], nx['y'])
    item = None; group = None
    for e in ev:
        k = e['k']
        if k == 'CH':
            cur = {'ch': e['v'][0], 'title_line': e['t'], 'page': e['pg'], 'items': []}
            chapters.append(cur); item = None; group = None
            continue
        if k == 'PSG':
            m = re.search(r'回答(第)?\s*([0-9]+)\s*[.．]?\s*(?:[～~－\-]\s*([0-9]+))?', e['t'])
            rng = (m.group(2) + ('～' + m.group(3) if m and m.group(3) else '')) if m else ''
            cur['items'].append({'type': 'passage', 'label': rng, 'stem': [(e['pg'], e['y']), e['end']], 'text': e['t']})
            item = None; group = None
            continue
        if k == 'GRP':
            group = {'type': 'group', 'num': e['v'][0], 'stem': [(e['pg'], e['y']), e['end']], 'subs': [], 'implicit': e.get('implicit', False)}
            cur['items'].append(group); item = group
            continue
        if k == 'Q':
            group = None
            item = {'type': 'q', 'num': e['v'][1], 'ans': e['v'][0], 'stem': [(e['pg'], e['y']), e['end']], 'jx': None, 'text': e['t']}
            cur['items'].append(item)
            continue
        if k == 'SUB':
            item = {'type': 'sub', 'num': e['v'][1], 'ans': e['v'][0], 'stem': [(e['pg'], e['y']), e['end']], 'jx': None, 'text': e['t']}
            group['subs'].append(item)
            continue
        if k == 'JX':
            if item is None:
                flags.append(f'ch{cur["ch"]}: 孤立解析 p{e["pg"]+1}')
                continue
            if item.get('jx'):
                # second 解析 line for same item: extend
                item['jx'][1] = e['end']
            else:
                item['jx'] = [(e['pg'], e['y']), e['end']]
    return doc, chapters, flags


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for sem in SEMS:
        doc, chapters, flags = build(sem)
        json.dump(chapters, open(f'{OUT}/{sem}.json', 'w'), ensure_ascii=False, indent=1)
        print('==', sem)
        for c in chapters:
            c_items = [it for it in c['items'] if it['type'] != 'passage']
            n_main = len(c_items)
            n_ans = sum(1 for it in c_items if it['type'] == 'q') + sum(len(it['subs']) for it in c_items if it['type'] == 'group')
            no_jx = [f"{it['num']}" for it in c_items if it['type'] == 'q' and not it['jx']] + \
                    [f"{it['num']}({s['num']})" for it in c_items if it['type'] == 'group' for s in it['subs'] if not s['jx']]
            nums = [it['num'] for it in c_items]
            print(f"  ch{c['ch']}: 題號 {nums[0] if nums else '-'}–{nums[-1] if nums else '-'}  主題數 {n_main}  作答數 {n_ans}  無解析 {no_jx}")
        for f in flags:
            print('  !', f)
