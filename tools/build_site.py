"""Build the static answer site.

Pipeline: parse 教用 → align to printed book numbering → analyse regions → render crops → HTML.
"""
import os, re, json, html, shutil, sys, collections
from parse import build, SEMS, SRC
from assets import Doc, analyse, render, answer_spans

SITE = '/home/claude/work/site'
ZOOM = 2.2
WEBP_Q = 72

SEMCODE = {'1上': '1a', '1下': '1b', '2上': '2a', '2下': '2b', '3上': '3a', '3下': '3b'}
VOLS = {
    1: {'title': '生物篇', 'full': '第一冊　國中自然．生物篇', 'grade': '國一', 'sems': ['1上', '1下'], 'en': 'Volume I · Life Science'},
    2: {'title': '理化上篇', 'full': '第二冊　國中自然．理化上篇', 'grade': '國二', 'sems': ['2上', '2下'], 'en': 'Volume II · Physical Science'},
    3: {'title': '理化下與地科篇', 'full': '第三冊　國中自然．理化下與地科篇', 'grade': '國三', 'sems': ['3上', '3下'], 'en': 'Volume III · Physics & Earth Science'},
}
VOLNUM = {1: '一', 2: '二', 3: '三'}
ROMAN = {1: 'Ⅰ', 2: 'Ⅱ', 3: 'Ⅲ'}
TITLES = {
    '1上': ['生命的觀察與細胞', '生物體的構造層次', '養分與消化作用', '運輸作用', '協調作用', '恆定性'],
    '1下': ['生殖', '遺傳', '生物的分類與演化', '生態系', '生物多樣性與保育'],
    '2上': ['物質的世界', '物質的形態與變化', '聲音與波動', '光與顏色', '溫度與熱', '原子與週期表'],
    '2下': ['化學反應', '氧化還原反應', '酸鹼鹽', '反應速率與化學平衡', '有機化合物', '氣體與壓力'],
    '3上': ['速度與運動', '力的作用', '功與能量', '電與電路', '水與大氣', '地球的構造與板塊', '天文與宇宙'],
    '3下': ['電化學', '電與磁的應用', '天氣與全球變遷', '環境保護與永續'],
}
SEM_VOL = {s: v for v, d in VOLS.items() for s in d['sems']}

align = json.load(open('/home/claude/work/data/book_align.json'))
E = html.escape
RE_SRC = re.compile(r'【\s*([^】]{2,20}?)\s*】')
RE_PICK = re.compile(r'(?:故選|故答案為|答案為|故答案選|應選|故本題選|故正確答案為)\s*[（(【]\s*([A-EＡ-Ｅ])\s*[)）】]')
FW = str.maketrans('ＡＢＣＤＥ', 'ABCDE')

report = {'answer_check': [], 'notes': [], 'images': 0, 'text_jx': 0, 'image_jx': 0, 'picks': 0}
# 教用版答案欄與解析、題意不符者（人工確認後更正）
ANSWER_FIX = {
    '3上|6|94': ('D', '教用版答案欄印為 (B)，但解析與題意（離中洋脊愈遠地殼愈老）皆指向 (D)，本站已更正為 (D)。'),
    '3下|4|26': ('B', '教用版答案欄印為 (A)，但解析與題意（臭氧層集中於離地表 20～30 公里）皆指向 (B)，本站已更正為 (B)。'),
}


def save_img(im, rel):
    path = os.path.join(SITE, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path, 'WEBP', quality=WEBP_Q, method=6)
    report['images'] += 1
    return rel, im.width, im.height


def src_tag(D, reg):
    res = analyse(D, reg, 'stem')
    txt = ''
    for s in res['segs']:
        txt += D.doc[s['pg']].get_text(clip=s['crop'])
    tags = RE_SRC.findall(re.sub(r'\s+', ' ', txt))
    tags = [re.sub(r'\s+', ' ', t).strip() for t in tags if re.search(r'\d', t) and re.search(r'基測|會考|聯測|測驗|試辦|補考|特招|模擬', t)]
    return tags[-1] if tags else '', res


def item_payload(D, sem, ch, obj, key, rel_base, ident):
    """stem image + 解析 for a q or sub"""
    stem_reg = [tuple(obj['stem'][0]), tuple(obj['jx'][0]) if obj.get('jx') else tuple(obj['stem'][1])]
    tag, S = src_tag(D, stem_reg)
    if not answer_spans(D, S, tuple(obj['stem'][0])):
        report.setdefault('no_answer_mask', []).append(key)
    im = render(D, S, zoom=ZOOM)
    stem = save_img(im, f'{rel_base}/{ident}-q.webp') if im else None
    jx = None
    if obj.get('jx'):
        J = analyse(D, obj['jx'], 'jx')
        if J['mode'] == 'text' and J.get('html'):
            jx = {'mode': 'text', 'html': J['html']}
            report['text_jx'] += 1
        else:
            jim = render(D, J, zoom=ZOOM)
            jx = {'mode': 'image', 'img': save_img(jim, f'{rel_base}/{ident}-a.webp') if jim else None}
            report['image_jx'] += 1
        # answer consistency
        picks = [p.translate(FW) for p in RE_PICK.findall(J.get('plain', ''))]
        if picks:
            report['picks'] += 1
        if picks and obj['ans'] not in picks:
            report['answer_check'].append({'key': key, 'ans': obj['ans'], 'jx_says': picks})
    ans, fix = obj['ans'], ''
    if key in ANSWER_FIX:
        ans, fix = ANSWER_FIX[key]
        report['notes'].append(f'{key} 答案更正：{fix}')
    return {'ans': ans, 'src': tag, 'stem': stem, 'jx': jx, 'fix': fix}


def build_data():
    data = []
    for sem in SEMS:
        _, chs, _ = build(sem)
        D = Doc(f'{SRC}/{sem}_教用.pdf')
        code = SEMCODE[sem]
        for c in chs:
            ch = c['ch']
            rel_base = f'assets/q/{code}/{ch:02d}'
            items = []
            seen = collections.Counter()
            seq = 0
            for it in c['items']:
                seq += 1
                if it['type'] == 'passage':
                    res = analyse(D, [tuple(it['stem'][0]), tuple(it['stem'][1])], 'stem')
                    im = render(D, res, zoom=ZOOM)
                    first = int(re.match(r'\d+', it['label']).group(0)) if re.match(r'\d+', it['label']) else 0
                    ident = f"p{first}"
                    items.append({'type': 'passage', 'label': it['label'], 'id': ident, 'order': (first - 0.5, seq),
                                  'img': save_img(im, f'{rel_base}/{ident}-p.webp') if im else None, 'page': None})
                    continue
                if it['type'] == 'q':
                    key = f"{sem}|{ch}|{it['num']}"
                    al = align.get(key, {})
                    label = al.get('label') or str(it['num'])
                    note = ''
                    if al.get('printed_typo') and label != str(it['num']):
                        note = f'題本此題誤印為「{label}.」（位於本章最後一題），實為第 {it["num"]} 題。'
                        report['notes'].append(f'{sem} 第{ch}章 {note}')
                        label = str(it['num'])
                    seen[label] += 1
                    ident = f'q{label}' + (f'-{seen[label]}' if seen[label] > 1 else '')
                    if seen[label] > 1:
                        note = f'題本與教用版此處皆重複印了兩次「{label}.」，這是第二個 {label} 題。'
                        report['notes'].append(f'{sem} 第{ch}章 {note}')
                    p = item_payload(D, sem, ch, it, key, rel_base, ident)
                    num = int(re.match(r'\d+', label).group(0))
                    if label != str(it['num']):
                        note = f'教用版原為第 {it["num"]} 題，本站依題本題號標示為第 {label} 題。'
                        report['notes'].append(f'{sem} 第{ch}章 {note}')
                    items.append({'type': 'q', 'label': label, 'id': ident, 'order': (num, seq), 'note': note,
                                  'page': al.get('page'), **p})
                else:
                    gkey = f"{sem}|{ch}|{it['num']}|g"
                    al = align.get(gkey, {})
                    label = al.get('label') or str(it['num'])
                    ident = f'q{label}'
                    note = ''
                    if label != str(it['num']):
                        note = f'教用版原為第 {it["num"]} 題，本站依題本題號標示為第 {label} 題。'
                        report['notes'].append(f'{sem} 第{ch}章 題組{note}')
                    gstem = None; gsrc = ''
                    if it['subs']:
                        gsrc, res = src_tag(D, [tuple(it['stem'][0]), tuple(it['subs'][0]['stem'][0])])
                        im = render(D, res, zoom=ZOOM)
                        gstem = save_img(im, f'{rel_base}/{ident}-g.webp') if im else None
                    subs = []
                    for s in it['subs']:
                        skey = f"{gkey}|{s['num']}"
                        sal = align.get(skey, {})
                        sid = f"{ident}-{s['num']}"
                        p = item_payload(D, sem, ch, s, skey, rel_base, sid)
                        subs.append({'num': s['num'], 'id': sid, 'page': sal.get('page'), **p})
                    num = int(label)
                    items.append({'type': 'group', 'label': label, 'id': ident, 'order': (num, seq), 'note': note,
                                  'gstem': gstem, 'gsrc': gsrc, 'subs': subs, 'page': al.get('page') or (subs[0]['page'] if subs else None)})
            items.sort(key=lambda x: x['order'])
            # passage pages: page of next item
            for i, x in enumerate(items):
                if x['type'] == 'passage' and i + 1 < len(items):
                    x['page'] = items[i + 1].get('page')
            # shared 解析 for plain questions without their own
            for i, x in enumerate(items):
                if x['type'] == 'q' and not x['jx']:
                    nxt = next((y for y in items[i + 1:] if y['type'] == 'q'), None)
                    if nxt:
                        x['shared_with'] = nxt['label']
            pages = [x['page'] for x in items if x.get('page')]
            n_ans = sum(1 if x['type'] == 'q' else len(x['subs']) for x in items if x['type'] != 'passage')
            data.append({'sem': sem, 'code': code, 'ch': ch, 'vol': SEM_VOL[sem], 'title': TITLES[sem][ch - 1],
                         'items': items, 'n': n_ans, 'p0': min(pages) if pages else None, 'p1': max(pages) if pages else None,
                         'slug': f'{code}-{ch:02d}'})
            print(sem, ch, 'items', len(items), 'answers', n_ans, file=sys.stderr)
    return data


# ---------------------------------------------------------------- HTML
FONTS = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&family=Noto+Serif+TC:wght@500;700;900&display=swap" rel="stylesheet">'


def page(title, body, depth=0, desc='典陸教育集團　國中自然歷屆會考考題　答案與詳解（題本配套網頁）', active=None):
    up = '../' * depth
    nav = ''.join(f'<a href="{up}vol{v}.html"{" aria-current=page" if active == v else ""}>第{VOLNUM[v]}冊<span>{VOLS[v]["title"]}</span></a>' for v in VOLS)
    return f'''<!doctype html>
<html lang="zh-Hant-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="description" content="{E(desc)}">
<meta name="theme-color" content="#1a3a56">
<meta name="color-scheme" content="light">
<title>{E(title)}</title>
<link rel="icon" href="{up}assets/favicon.svg" type="image/svg+xml">
{FONTS}
<link rel="stylesheet" href="{up}assets/site.css?v=3">
</head>
<body>
<a class="skip" href="#main">跳到主要內容</a>
<header class="brand-bar">
  <a class="brand-bar-left" href="{up}index.html" aria-label="典陸教育集團 首頁">
    <span class="brand-bar-zh">典 陸 教 育 集 團</span>
    <span class="brand-bar-en">DANLU&nbsp;&nbsp;EDUCATION&nbsp;&nbsp;GROUP</span>
  </a>
  <span class="brand-bar-slogan">升 學 的 事 &nbsp;&nbsp; 典 陸 解 決</span>
</header>
<nav class="volnav" aria-label="冊別">{nav}</nav>
<main id="main">
{body}
</main>
<footer class="site-foot">
  <div class="brand-tagline">專 業 升 國 中 &nbsp;·&nbsp; 升 高 中 &nbsp;·&nbsp; 升 大 學</div>
  <p class="foot-note">本站為《國中自然 歷屆會考．大考考題精選》題本配套之答案與詳解。題號依題本印刷標示。<br>© 典陸教育集團 教研中心　<a href="https://www.danlu-education.com/" rel="noopener">danlu-education.com</a></p>
</footer>
<script src="{up}assets/site.js?v=3" defer></script>
</body>
</html>
'''


def img_tag(im, up, alt, cls='crop', lazy=True):
    if not im:
        return ''
    rel, w, h = im
    if lazy:
        return f'<img class="{cls}" data-src="{up}{rel}" width="{w}" height="{h}" alt="{E(alt)}">'
    return f'<img class="{cls}" src="{up}{rel}" width="{w}" height="{h}" alt="{E(alt)}" loading="lazy" decoding="async">'


def jx_html(jx, up, alt):
    if not jx:
        return ''
    if jx['mode'] == 'text':
        return f'<div class="jx">{jx["html"]}</div>'
    return f'<div class="jx jx-img"><button class="zoom" type="button" aria-label="放大解析圖">{img_tag(jx["img"], up, alt, "crop", lazy=False)}</button></div>'


def bubbles(ans, label, anchor):
    cells = ''.join(f'<i class="b{" on" if L in ans else ""}">{L}</i>' for L in 'ABCD')
    return f'<li><a href="#{anchor}" aria-label="第 {E(label)} 題，答案 {ans}"><b class="n">{E(label)}</b><span class="bub" aria-hidden="true">{cells}</span></a></li>'


def mark(ans):
    return f'<span class="mark" aria-label="答案 {ans}"><span class="mk">{ans}</span></span>'


def meta(src, pg):
    bits = []
    if src:
        bits.append(f'<span class="src">{E(src)}</span>')
    if pg:
        bits.append(f'<span class="pg">題本 p.{pg}</span>')
    return f'<div class="meta">{"".join(bits)}</div>' if bits else ''


def chapter_html(c, prev, nxt):
    up = '../'
    v = c['vol']
    # answer sheet
    sheet = []
    for x in c['items']:
        if x['type'] == 'q':
            sheet.append(bubbles(x['ans'], x['label'], x['id']))
        elif x['type'] == 'group':
            for s in x['subs']:
                sheet.append(bubbles(s['ans'], f"{x['label']}({s['num']})", s['id']))
    rows = []
    for x in c['items']:
        if x['type'] == 'passage':
            rows.append(f'''<section class="q psg" id="{x['id']}">
  <div class="qn"><span class="tag">閱讀</span></div>
  <div class="qb">
    <h3 class="psg-h">共同閱讀文章（第 {E(x['label'])} 題）</h3>
    {meta('', x.get('page'))}
    <details class="stem"><summary>看文章</summary>{img_tag(x['img'], up, '閱讀文章')}</details>
  </div>
</section>''')
            continue
        if x['type'] == 'q':
            note = ''.join(f'<p class="note">{E(t)}</p>' for t in (x.get('note'), x.get('fix')) if t)
            shared = f'<p class="shared">本題解析與第 {E(x["shared_with"])} 題合併，請見第 <a href="#q{E(x["shared_with"])}">{E(x["shared_with"])}</a> 題。</p>' if x.get('shared_with') else ''
            rows.append(f'''<section class="q" id="{x['id']}">
  <div class="qn"><span class="num">{E(x['label'])}</span></div>
  <div class="qb">
    <div class="qh">{mark(x['ans'])}{meta(x['src'], x.get('page'))}</div>
    {note}{jx_html(x['jx'], up, f"第{x['label']}題解析")}{shared}
    <details class="stem"><summary>看題目</summary>{img_tag(x['stem'], up, f"第{x['label']}題題目")}</details>
  </div>
</section>''')
            continue
        # group
        subs = []
        pending = []
        for s in x['subs']:
            pending.append(s)
            if not s['jx'] and s is not x['subs'][-1]:
                continue
            for k, ps in enumerate(pending):
                last = k == len(pending) - 1
                merged = '' if last or len(pending) == 1 else f'<p class="shared">解析與第 ({pending[-1]["num"]}) 小題合併，見下方。</p>'
                head = ''
                if last and len(pending) > 1:
                    head = f'<p class="jx-h">第 {"、".join("(" + str(p["num"]) + ")" for p in pending)} 小題解析</p>'
                subs.append(f'''<div class="sub" id="{ps['id']}">
      <div class="qh"><span class="subn">({ps['num']})</span>{mark(ps['ans'])}{meta(ps['src'], ps.get('page'))}</div>
      {''.join(f'<p class="note">{E(ps["fix"])}</p>' for _ in [0] if ps.get('fix'))}{merged}{head}{jx_html(ps['jx'], up, f"第{x['label']}({ps['num']})題解析") if last else ''}
      <details class="stem"><summary>看題目</summary>{img_tag(ps['stem'], up, f"第{x['label']}({ps['num']})題題目")}</details>
    </div>''')
            pending = []
        note = f'<p class="note">{E(x["note"])}</p>' if x.get('note') else ''
        rows.append(f'''<section class="q grp" id="{x['id']}">
  <div class="qn"><span class="num">{E(x['label'])}</span><span class="tag">題組</span></div>
  <div class="qb">
    {meta(x.get('gsrc', ''), x.get('page'))}{note}
    <details class="stem gstem"><summary>看題組文章</summary>{img_tag(x['gstem'], up, f"第{x['label']}題題組文章")}</details>
    {''.join(subs)}
  </div>
</section>''')
    pager = '<nav class="pager" aria-label="章節切換">'
    pager += f'<a class="prev" href="{prev["slug"]}.html"><small>上一章</small>{E(prev["sem"])}　第 {prev["ch"]} 章　{E(prev["title"])}</a>' if prev else '<span></span>'
    pager += f'<a class="next" href="{nxt["slug"]}.html"><small>下一章</small>{E(nxt["sem"])}　第 {nxt["ch"]} 章　{E(nxt["title"])}</a>' if nxt else '<span></span>'
    pager += '</nav>'
    pr = f'題本 p.{c["p0"]}–{c["p1"]}' if c['p0'] else ''
    body = f'''<div class="crumbs"><a href="../index.html">首頁</a><span>›</span><a href="../vol{v}.html">第{VOLNUM[v]}冊　{VOLS[v]['title']}</a><span>›</span>{E(c['sem'])}</div>
<header class="ch-head">
  <p class="ch-k">{E(c['sem'])}學期　第 {c['ch']} 章</p>
  <h1>{E(c['title'])}</h1>
  <p class="ch-meta"><span>{c['n']} 題</span><span>{pr}</span></p>
</header>
<div class="tools" id="tools">
  <form class="jump" role="search" onsubmit="return false">
    <label for="jumpn">跳到第</label><input id="jumpn" inputmode="numeric" pattern="[0-9]*" maxlength="3" autocomplete="off" placeholder="—"><label for="jumpn">題</label>
  </form>
  <button type="button" class="mask-t" aria-pressed="false">遮住答案</button>
  <a class="to-sheet" href="#sheet">答案卡</a>
</div>
<section class="sheet" id="sheet" aria-labelledby="sheet-h">
  <h2 id="sheet-h">答案卡</h2>
  <p class="sheet-tip">點題號可跳到該題詳解。開啟「遮住答案」後，點一下塗卡格才會顯示答案。</p>
  <ol class="bubbles">{''.join(sheet)}</ol>
</section>
<section class="list" aria-labelledby="list-h">
  <h2 id="list-h">詳解</h2>
  {''.join(rows)}
</section>
{pager}'''
    return page(f'{c["sem"]} 第{c["ch"]}章 {c["title"]}｜國中自然歷屆考題詳解｜典陸教育', body, depth=1, active=v,
                desc=f'{c["sem"]} 第{c["ch"]}章 {c["title"]}　歷屆會考、基測考題答案與詳解，共 {c["n"]} 題。')


def vol_html(v, chapters):
    d = VOLS[v]
    groups = ''
    for sem in d['sems']:
        rows = ''
        for c in [c for c in chapters if c['sem'] == sem]:
            pr = f'p.{c["p0"]}' if c['p0'] else ''
            rows += f'<li><a href="ch/{c["slug"]}.html"><span class="toc-n">第 {c["ch"]} 章</span><span class="toc-t">{E(c["title"])}</span><span class="toc-l" aria-hidden="true"></span><span class="toc-c">{c["n"]} 題</span><span class="toc-p">{pr}</span></a></li>'
        groups += f'<section class="sem"><h2>{sem}學期</h2><ol class="toc">{rows}</ol></section>'
    total = sum(c['n'] for c in chapters if c['vol'] == v)
    body = f'''<div class="crumbs"><a href="index.html">首頁</a><span>›</span>第{VOLNUM[v]}冊</div>
<header class="vol-head v{v}">
  <span class="vol-roman" aria-hidden="true">{ROMAN[v]}</span>
  <div>
    <p class="vol-k">第{VOLNUM[v]}冊　適用{d['grade']}</p>
    <h1>{d['title']}</h1>
    <p class="vol-meta">{len([c for c in chapters if c['vol'] == v])} 章，共 {total} 題</p>
  </div>
</header>
<p class="toc-tip">右側頁碼為題本頁尾的頁碼；題號也與題本相同。</p>
<div class="toc-wrap">{groups}</div>'''
    return page(f'第{VOLNUM[v]}冊 {d["title"]}｜國中自然歷屆考題詳解｜典陸教育', body, active=v,
                desc=f'{d["full"]}　各章答案與詳解目錄。')


def index_html(chapters, notes):
    cards = ''
    for v, d in VOLS.items():
        n = sum(c['n'] for c in chapters if c['vol'] == v)
        k = len([c for c in chapters if c['vol'] == v])
        cards += f'''<a class="book v{v}" href="vol{v}.html">
  <span class="book-band"><span class="book-roman">{ROMAN[v]}</span></span>
  <span class="book-body">
    <span class="book-k">第{VOLNUM[v]}冊　{d['grade']}</span>
    <span class="book-t">{d['title']}</span>
    <span class="book-m">{k} 章　{n} 題</span>
  </span>
</a>'''
    notes_html = ''.join(f'<li>{E(n)}</li>' for n in notes)
    body = f'''<section class="hero">
  <h1>國中自然　歷屆會考考題<br>答案與詳解</h1>
  <p class="lead">對照手上的題本，選冊別、選章節，再依題號找答案。每題附解析，需要時可展開原題。</p>
</section>
<section class="books" aria-label="選擇冊別">{cards}</section>
<section class="howto">
  <h2>使用方式</h2>
  <ol>
    <li><b>選冊別</b>　題本封面上的Ⅰ、Ⅱ、Ⅲ。</li>
    <li><b>選章節</b>　目錄上的頁碼即題本頁尾頁碼。</li>
    <li><b>對答案</b>　先看「答案卡」，再往下看每題解析。</li>
  </ol>
</section>
<section class="errata" id="errata">
  <h2>題號與答案對照說明</h2>
  <p>以下幾處題本題號與原始教用版不同，或教用版答案欄與解析不一致，本站已校正：</p>
  <ul>{notes_html}</ul>
</section>'''
    return page('國中自然 歷屆會考考題 答案與詳解｜典陸教育集團', body)


CSS = r'''
:root{
  --navy:#1a3a56; --navy-2:#24507a; --navy-ink:#13283c;
  --gold:#a48748; --gold-soft:#d8d2bf; --gold-wash:#f6f2e7;
  --sumi:#4d4d54; --ink:#1f2328; --muted:#6b6f76;
  --red:#c0392b; --red-wash:#fbecea;
  --bg:#ffffff; --band:#f3f5f8; --line:#e3e6ea;
  --serif:"Noto Serif TC","Songti TC","PMingLiU",serif;
  --sans:"Noto Sans TC","PingFang TC","Microsoft JhengHei",system-ui,sans-serif;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-padding-top:72px}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.75 var(--sans);font-feature-settings:"palt" 0}
img{max-width:100%;height:auto;display:block}
a{color:var(--navy-2)}
.skip{position:absolute;left:-999px;top:0;background:#fff;padding:8px 12px;z-index:99}
.skip:focus{left:8px}
:focus-visible{outline:3px solid var(--gold);outline-offset:2px}

/* ---- CIS brand bar (danlu-brand-chrome) ---- */
.brand-bar{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 16px;max-width:1080px;margin:0 auto;border-bottom:1px solid var(--gold-soft)}
.brand-bar-left{display:flex;flex-direction:column;gap:2px;text-decoration:none}
.brand-bar-zh{color:#4d4d54;letter-spacing:.3em;font-size:14px;line-height:1.3}
.brand-bar-en{color:#a48748;letter-spacing:.22em;font-size:10.5px;font-weight:400;line-height:1.3;white-space:nowrap}
.brand-bar-slogan{color:#a48748;letter-spacing:.25em;font-size:12px;white-space:nowrap}
.brand-tagline{text-align:center;padding:16px;font-size:12px;color:#4d4d54;letter-spacing:.4em;border-top:1px solid var(--gold-soft);max-width:1080px;margin:0 auto}
@media (max-width:420px){.brand-bar-slogan{font-size:11px;letter-spacing:.12em}.brand-bar-zh{letter-spacing:.22em;font-size:13px}.brand-bar-en{letter-spacing:.12em;font-size:9.5px}}

/* ---- volume nav ---- */
.volnav{display:flex;max-width:1080px;margin:0 auto;padding:0 8px;overflow-x:auto;scrollbar-width:none}
.volnav::-webkit-scrollbar{display:none}
.volnav a{flex:1 0 auto;text-align:center;padding:10px 12px 9px;color:var(--sumi);text-decoration:none;font-size:15px;border-bottom:3px solid transparent;white-space:nowrap}
.volnav a span{margin-left:.4em;color:var(--muted);font-size:13px}
.volnav a[aria-current]{color:var(--navy);border-bottom-color:var(--navy);font-weight:700}
.volnav a:hover{color:var(--navy)}
main{max-width:1080px;margin:0 auto;padding:0 16px 40px}
.crumbs{font-size:13px;color:var(--muted);padding:14px 0 0;display:flex;gap:.5em;flex-wrap:wrap}
.crumbs a{color:var(--muted)}

/* ---- home ---- */
.hero{padding:40px 0 24px;border-bottom:1px solid var(--line)}
.hero h1{font-family:var(--serif);font-weight:900;font-size:clamp(30px,7vw,52px);line-height:1.25;letter-spacing:.04em;margin:0 0 14px;color:var(--navy-ink)}
.hero .lead{max-width:34em;color:var(--sumi);margin:0;font-size:16px}
.books{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;padding:28px 0 8px}
.book{display:flex;flex-direction:column;text-decoration:none;color:inherit;border:1px solid var(--line);background:#fff;min-height:230px;transition:transform .15s ease,border-color .15s}
.book:hover{border-color:var(--gold);transform:translateY(-2px)}
.book-band{background:var(--navy);border-bottom:4px solid var(--gold);height:104px;display:flex;align-items:center;padding:0 20px}
.book-roman{font-family:var(--serif);color:#fff;font-size:58px;line-height:1;font-weight:500}
.book-body{display:flex;flex-direction:column;padding:28px 18px 18px;gap:4px}
.book-k{font-size:13px;color:var(--muted)}
.book-t{font-family:var(--serif);font-size:24px;font-weight:700;color:var(--navy-ink);line-height:1.35}
.book-m{font-size:14px;color:var(--gold);margin-top:auto;padding-top:10px}
.howto,.errata{padding:28px 0 4px}
.howto h2,.errata h2{font-family:var(--serif);font-size:20px;margin:0 0 10px;color:var(--navy-ink)}
.howto ol{margin:0;padding-left:1.4em;color:var(--sumi)}
.howto li{margin:2px 0}
.howto b{color:var(--ink)}
.errata p{color:var(--sumi);margin:0 0 6px;font-size:15px}
.errata ul{margin:0;padding-left:1.2em;color:var(--sumi);font-size:15px}
.errata li{margin:4px 0}
@media (max-width:720px){
  .books{grid-template-columns:1fr;gap:12px}
  .book{flex-direction:row;min-height:0}
  .book-band{height:auto;width:76px;flex:0 0 76px;border-bottom:0;border-right:4px solid var(--gold);align-items:center;justify-content:center;padding:0}
  .book-roman{transform:none;font-size:44px}
  .book-body{padding:14px 16px}
  .book-t{font-size:21px}
  .book-m{padding-top:4px}
}

/* ---- volume TOC ---- */
.vol-head{display:flex;gap:18px;align-items:center;padding:22px 0 18px;border-bottom:1px solid var(--line)}
.vol-roman{font-family:var(--serif);font-size:56px;line-height:1;color:#fff;background:var(--navy);width:84px;height:96px;display:flex;align-items:center;justify-content:center;border-bottom:4px solid var(--gold);flex:0 0 auto}
.vol-k{margin:0;color:var(--muted);font-size:14px}
.vol-head h1{font-family:var(--serif);font-size:clamp(26px,6vw,38px);margin:2px 0 4px;color:var(--navy-ink);line-height:1.25}
.vol-meta{margin:0;color:var(--sumi);font-size:14px}
.toc-tip{margin:14px 0 0;font-size:13px;color:var(--muted)}
.sem h2{font-family:var(--serif);font-size:19px;color:var(--navy);margin:26px 0 6px;padding-left:10px;border-left:4px solid var(--gold)}
.toc{list-style:none;margin:0;padding:0}
.toc a{display:flex;align-items:baseline;gap:10px;padding:13px 4px;border-bottom:1px solid var(--line);text-decoration:none;color:var(--ink)}
.toc a:hover{background:var(--band)}
.toc-n{color:var(--muted);font-size:14px;flex:0 0 auto;min-width:4.2em}
.toc-t{font-family:var(--serif);font-size:18px;font-weight:700;flex:0 1 auto}
.toc-l{flex:1 1 auto;border-bottom:1px dotted #b9b2a0;transform:translateY(-5px);min-width:12px}
.toc-c{flex:0 0 auto;color:var(--sumi);font-size:14px}
.toc-p{flex:0 0 auto;color:var(--gold);font-size:14px;min-width:3.6em;text-align:right}
@media (max-width:480px){.toc-n{min-width:3.6em;font-size:13px}.toc-t{font-size:16.5px}.toc-c{display:none}}

/* ---- chapter ---- */
.ch-head{padding:14px 0 16px}
.ch-k{margin:0;color:var(--gold);font-size:15px;letter-spacing:.06em}
.ch-head h1{font-family:var(--serif);font-weight:900;font-size:clamp(28px,7vw,42px);line-height:1.25;margin:2px 0 8px;color:var(--navy-ink)}
.ch-meta{margin:0;display:flex;gap:16px;color:var(--sumi);font-size:14px}
.tools{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.96);backdrop-filter:saturate(1.4) blur(6px);display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--line);border-top:1px solid var(--line)}
.jump{display:flex;align-items:center;gap:6px;font-size:14px;color:var(--sumi)}
.jump input{width:3.4em;font:inherit;font-size:16px;text-align:center;padding:5px 4px;border:1px solid #c9ced6;border-radius:4px;color:var(--ink)}
.mask-t,.to-sheet{font:inherit;font-size:14px;border:1px solid #c9ced6;background:#fff;color:var(--sumi);padding:5px 10px;border-radius:4px;cursor:pointer;text-decoration:none;white-space:nowrap}
.mask-t[aria-pressed=true]{background:var(--navy);border-color:var(--navy);color:#fff}
.to-sheet{margin-left:auto}
.sheet{padding:18px 0 10px}
.sheet h2,.list h2{font-family:var(--serif);font-size:20px;color:var(--navy-ink);margin:0 0 4px}
.sheet-tip{margin:0 0 12px;font-size:13px;color:var(--muted)}
.bubbles{list-style:none;margin:0;padding:12px 10px;columns:170px;column-gap:14px;column-rule:1px solid var(--gold-soft);background:var(--gold-wash);border:1px solid var(--gold-soft)}
.bubbles li{break-inside:avoid}
.bubbles a{display:flex;align-items:center;gap:8px;padding:4px 4px;text-decoration:none;color:var(--ink);border-radius:3px}
.bubbles a:hover{background:#fff}
.bubbles .n{font-family:var(--serif);font-weight:700;min-width:3.3em;text-align:right;font-size:15px;color:var(--navy-ink)}
.bub{display:flex;gap:5px}
.bub .b{font-style:normal;width:22px;height:22px;border:1.5px solid #b45a52;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#b45a52;font-family:var(--sans);line-height:1}
.bub .b.on{background:var(--ink);border-color:var(--ink);color:#fff}
.list{padding-top:18px}
.q{display:grid;grid-template-columns:64px 1fr;gap:0 14px;padding:18px 0;border-top:1px solid var(--line)}
.qn{display:flex;flex-direction:column;align-items:flex-end;gap:4px;padding-top:2px}
.num{font-family:var(--serif);font-weight:900;font-size:30px;line-height:1;color:var(--navy-ink)}
.tag{font-size:12px;color:var(--gold);border:1px solid var(--gold-soft);padding:0 6px;border-radius:2px;white-space:nowrap}
.qb{min-width:0}
.qh{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:6px}
.mark{display:inline-flex;align-items:center;justify-content:center;width:38px;height:38px;border:2.5px solid var(--red);border-radius:50%;color:var(--red);font-family:"Times New Roman",var(--serif);font-weight:700;font-size:21px;line-height:1;transform:rotate(-6deg);flex:0 0 auto;cursor:default}
.meta{display:flex;gap:10px;flex-wrap:wrap;font-size:13px;color:var(--muted)}
.meta .src{color:var(--sumi);background:var(--band);padding:1px 8px;border-radius:2px}
.jx{color:var(--ink);font-size:16.5px;line-height:1.85;max-width:40em}
.jx p{margin:0 0 6px}
.jx sub,.jx sup{font-size:.68em;line-height:0}
.jx-img .zoom{display:block;padding:0;margin:4px 0;border:1px solid var(--line);background:#fff;cursor:zoom-in;max-width:100%}
.jx-img .crop{width:100%;max-width:720px}
.jx-h{margin:8px 0 2px;font-size:13px;color:var(--gold)}
.note{margin:0 0 8px;font-size:14px;color:#7a5b16;background:var(--gold-wash);border-left:3px solid var(--gold);padding:6px 10px}
.shared{margin:2px 0 6px;font-size:14px;color:var(--sumi)}
details.stem{margin-top:8px}
details.stem summary{display:inline-flex;align-items:center;gap:6px;cursor:pointer;font-size:14px;color:var(--navy-2);padding:3px 0;list-style:none;user-select:none}
details.stem summary::-webkit-details-marker{display:none}
details.stem summary::before{content:"";width:7px;height:7px;border-right:2px solid currentColor;border-bottom:2px solid currentColor;transform:rotate(-45deg);transition:transform .15s}
details.stem[open] summary::before{transform:rotate(45deg) translate(-1px,-1px)}
details.stem .crop{margin-top:6px;border:1px solid var(--line);max-width:100%;width:720px}
.grp .sub{padding:12px 0 4px;border-top:1px dashed var(--line);margin-top:10px}
.grp .sub:first-of-type{border-top:0}
.subn{font-family:var(--serif);font-weight:700;font-size:18px;color:var(--navy-ink)}
.gstem{margin:0 0 4px}
.psg .psg-h{font-family:var(--serif);font-size:17px;margin:2px 0 4px;color:var(--navy-ink)}
:target{animation:hl 1.6s ease-out}
@keyframes hl{0%{background:var(--gold-wash)}100%{background:transparent}}
/* masked answers */
body.masked .bub .b.on{background:transparent;color:#b45a52;border-color:#b45a52}
body.masked .bubbles li.show .b.on{background:var(--ink);border-color:var(--ink);color:#fff}
body.masked .mark .mk{visibility:hidden}
body.masked .mark{cursor:pointer;border-style:dashed}
body.masked .mark.show .mk{visibility:visible}
body.masked .mark.show{border-style:solid}
body.masked .jx,body.masked .jx-img,body.masked .jx-h{filter:blur(6px);pointer-events:none;user-select:none}
body.masked .qb.show .jx,body.masked .qb.show .jx-img,body.masked .sub.show .jx,body.masked .sub.show .jx-img,body.masked .qb.show .jx-h{filter:none;pointer-events:auto}
.pager{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:28px 0 0}
.pager a{display:flex;flex-direction:column;padding:12px 14px;border:1px solid var(--line);text-decoration:none;color:var(--ink);font-family:var(--serif);font-size:15px}
.pager a small{font-family:var(--sans);font-size:12px;color:var(--gold)}
.pager .next{text-align:right}
.pager a:hover{border-color:var(--gold)}
.site-foot{margin-top:24px;background:#fff}
.foot-note{max-width:1080px;margin:0 auto;padding:0 16px 28px;text-align:center;font-size:12px;color:var(--muted);line-height:1.8}
.foot-note a{color:var(--muted)}
/* lightbox */
.lb{position:fixed;inset:0;background:rgba(19,40,60,.92);z-index:100;display:flex;align-items:center;justify-content:center;padding:12px;overflow:auto}
.lb img{max-width:none;width:min(1600px,220vw);background:#fff}
.lb button{position:fixed;top:10px;right:10px;font:inherit;font-size:15px;background:#fff;border:0;padding:8px 14px;border-radius:4px;cursor:pointer}
@media (min-width:720px){.lb img{width:min(1400px,96vw)}}
@media (max-width:560px){
  main{padding:0 14px 32px}
  .q{grid-template-columns:44px 1fr;gap:0 10px;padding:16px 0}
  .num{font-size:24px}
  .mark{width:34px;height:34px;font-size:19px}
  .bubbles{columns:2;column-gap:6px;padding:8px 4px}
  .volnav a span{display:none}
  .bubbles .n{min-width:2.7em;font-size:14px}
  .bub{gap:3px}
  .bub .b{width:19px;height:19px;font-size:10px}
  .jx{font-size:16px}
  .tools{gap:8px}
  .mask-t,.to-sheet{padding:5px 8px;font-size:13px}
}
@media (max-width:360px){.bub .b{width:17px;height:17px}.bubbles .n{min-width:2.4em}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
@media print{.tools,.volnav,.pager,details.stem summary{display:none}.q{break-inside:avoid}}
'''

JS = r'''
(function(){
  // lazy images inside <details>
  document.querySelectorAll('details.stem').forEach(function(d){
    d.addEventListener('toggle',function(){
      if(d.open){d.querySelectorAll('img[data-src]').forEach(function(im){im.src=im.getAttribute('data-src');im.removeAttribute('data-src');});}
    });
  });
  // jump to question
  var inp=document.getElementById('jumpn');
  if(inp){
    var go=function(){
      var v=(inp.value||'').trim(); if(!v) return;
      var el=document.getElementById('q'+v)||document.getElementById('q'+v+'-1')||document.getElementById('p'+v);
      if(el){el.scrollIntoView({behavior:'smooth',block:'start'}); history.replaceState(null,'','#'+el.id); inp.blur();}
      else{inp.setCustomValidity('本章沒有第 '+v+' 題'); inp.reportValidity(); setTimeout(function(){inp.setCustomValidity('')},1500);}
    };
    inp.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();go();}});
    inp.addEventListener('change',go);
  }
  // mask answers
  var btn=document.querySelector('.mask-t');
  var KEY='danlu-cap-mask';
  function setMask(on){
    document.body.classList.toggle('masked',on);
    if(btn){btn.setAttribute('aria-pressed',on?'true':'false'); btn.textContent=on?'顯示答案':'遮住答案';}
    document.querySelectorAll('.show').forEach(function(x){x.classList.remove('show')});
    try{localStorage.setItem(KEY,on?'1':'0')}catch(e){}
  }
  if(btn){
    var init=false; try{init=localStorage.getItem(KEY)==='1'}catch(e){}
    setMask(init);
    btn.addEventListener('click',function(){setMask(!document.body.classList.contains('masked'))});
  }
  document.addEventListener('click',function(e){
    if(!document.body.classList.contains('masked')) return;
    var li=e.target.closest('.bubbles li');
    if(li){ if(!li.classList.contains('show')){e.preventDefault(); li.classList.add('show');} return; }
    var m=e.target.closest('.mark');
    if(m){ m.classList.add('show'); var box=m.closest('.sub')||m.closest('.qb'); if(box) box.classList.add('show'); }
  });
  // lightbox for 解析 images
  document.addEventListener('click',function(e){
    var z=e.target.closest('.zoom'); if(!z) return;
    var im=z.querySelector('img'); if(!im) return;
    var lb=document.createElement('div'); lb.className='lb'; lb.setAttribute('role','dialog'); lb.setAttribute('aria-label','放大檢視');
    var big=document.createElement('img'); big.src=im.currentSrc||im.src; big.alt=im.alt;
    var close=document.createElement('button'); close.type='button'; close.textContent='關閉';
    lb.appendChild(big); lb.appendChild(close); document.body.appendChild(lb); close.focus();
    var done=function(){lb.remove(); z.focus();};
    close.addEventListener('click',done);
    lb.addEventListener('click',function(ev){if(ev.target===lb) done();});
    document.addEventListener('keydown',function k(ev){if(ev.key==='Escape'){done();document.removeEventListener('keydown',k);}});
  });
})();
'''

FAVICON = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="10" fill="#1a3a56"/><rect y="54" width="64" height="5" fill="#a48748"/><text x="32" y="43" font-family="serif" font-size="34" font-weight="700" fill="#fff" text-anchor="middle">典</text></svg>'''


def main():
    if os.path.exists(SITE):
        shutil.rmtree(SITE)
    os.makedirs(SITE)
    data = build_data()
    json.dump(data, open('/home/claude/work/data/site_data.json', 'w'), ensure_ascii=False)
    write_all(data)


def write_all(data):
    os.makedirs(f'{SITE}/ch', exist_ok=True)
    os.makedirs(f'{SITE}/assets', exist_ok=True)
    open(f'{SITE}/assets/site.css', 'w').write(CSS)
    open(f'{SITE}/assets/site.js', 'w').write(JS)
    open(f'{SITE}/assets/favicon.svg', 'w').write(FAVICON)
    for i, c in enumerate(data):
        prev = data[i - 1] if i > 0 else None
        nxt = data[i + 1] if i + 1 < len(data) else None
        open(f'{SITE}/ch/{c["slug"]}.html', 'w').write(chapter_html(c, prev, nxt))
    for v in VOLS:
        open(f'{SITE}/vol{v}.html', 'w').write(vol_html(v, data))
    notes = [
        '第一冊　1上 第3章：題本最後一題印為「36.」，實為第 51 題，答案請看本站第 51 題。',
        '第二冊　2上 第4章：題本第 30 題（凸透鏡與凹透鏡成像）與第 31 題（太陽能題組）順序和教用版對調，本站已依題本順序排列。',
        '第三冊　3下 第3章：題本與教用版都印了兩個「97.」，本站分別標示，第二個 97 題附註說明。',
        '答案更正　3上 第6章 第 94 題：教用版答案欄為 (B)，與解析不符，正確答案為 (D)。',
        '答案更正　3下 第4章 第 26 題：教用版答案欄為 (A)，與解析不符，正確答案為 (B)。',
    ]
    open(f'{SITE}/index.html', 'w').write(index_html(data, notes))
    # legacy chapter URLs from the old site → redirect stubs
    for c in data:
        legacy = f'{SITE}/ch/vol{c["vol"]}/{c["sem"]}_ch{c["ch"]:02d}'
        os.makedirs(legacy, exist_ok=True)
        open(f'{legacy}/index.html', 'w').write(f'<!doctype html><meta charset="utf-8"><title>移至新頁面</title><meta http-equiv="refresh" content="0; url=../../{c["slug"]}.html"><link rel="canonical" href="../../{c["slug"]}.html"><p><a href="../../{c["slug"]}.html">{E(c["sem"])} 第 {c["ch"]} 章 {E(c["title"])}</a></p>')
    open(f'{SITE}/404.html', 'w').write('''<!doctype html><html lang="zh-Hant-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>找不到頁面｜典陸教育</title>
<style>body{margin:0;font:16px/1.7 "Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif;color:#1f2328;background:#fff}.b{max-width:640px;margin:0 auto;padding:48px 20px}.z{color:#4d4d54;letter-spacing:.3em;font-size:14px}.e{color:#a48748;letter-spacing:.22em;font-size:11px}h1{font-family:"Noto Serif TC",serif;color:#13283c;font-size:30px;margin:32px 0 8px}a{color:#24507a}</style></head>
<body><div class="b"><div class="z">典 陸 教 育 集 團</div><div class="e">DANLU&nbsp;&nbsp;EDUCATION&nbsp;&nbsp;GROUP</div><h1>找不到這個頁面</h1><p>網址可能已更新，請回到<a id="home" href="/">首頁</a>重新選擇冊別與章節。</p></div>
<script>(function(){var p=location.pathname.split('/');var base=(location.hostname.endsWith('github.io')&&p.length>2)?'/'+p[1]+'/':'/';document.getElementById('home').href=base;})();</script></body></html>''')
    open(f'{SITE}/.nojekyll', 'w').write('')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'html':
        write_all(json.load(open('/home/claude/work/data/site_data.json')))
    else:
        main()
        json.dump(report, open('/home/claude/work/data/build_report.json', 'w'), ensure_ascii=False, indent=1)
        print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in report.items()}, ensure_ascii=False))
