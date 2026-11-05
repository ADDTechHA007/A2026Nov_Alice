"""Render the checked-in Chinese Markdown user guide using its small Markdown subset."""
from pathlib import Path
import html
import re

ROOT = Path(__file__).resolve().parent
SECTION_IDS = {1: "start", 2: "import", 3: "types", 4: "fields", 5: "handoffs", 6: "approvals", 7: "locks", 8: "factory", 9: "shipping", 10: "local", 11: "processing", 12: "notes", 13: "faq", 14: "evidence", 15: "limits"}


def inline(text):
    tokens = []
    def replace(match):
        raw = match.group()
        if raw.startswith("["):
            link = re.fullmatch(r"\[([^]]+)\]\(([^)]+)\)", raw)
            value = '<a href="' + html.escape(link[2], quote=True) + '">' + html.escape(link[1]) + '</a>'
        elif raw.startswith("**"):
            value = '<strong>' + html.escape(raw[2:-2]) + '</strong>'
        else:
            value = '<code>' + html.escape(raw[1:-1]) + '</code>'
        tokens.append(value)
        return f"\x00{len(tokens)-1}\x00"
    text = re.sub(r"\[[^]]+\]\([^)]+\)|\*\*[^*]+\*\*|`[^`]+`", replace, text)
    text = html.escape(text)
    return re.sub(r"\x00(\d+)\x00", lambda m: tokens[int(m[1])], text)


def build():
    lines = (ROOT / "使用说明-初稿.md").read_text(encoding="utf-8").splitlines()
    out, toc = [], []
    index, section_open = 2, False
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("## "):
            if section_open:
                out.append('</section>')
            title = line[3:]
            sid = SECTION_IDS[int(re.match(r"\d+", title)[0])]
            toc.append(f'<a href="#{sid}">{html.escape(title)}</a>')
            out.append(f'<section id="{sid}"><h2>{html.escape(title)}</h2>')
            section_open = True
            if sid == 'handoffs':
                out.append('<div id="manual-flows" class="manual-flows">下面列出当前三条流程；服务在线时此处显示各节点负责人。</div>')
        elif line.startswith("### "):
            out.append('<h3>' + inline(line[4:]) + '</h3>')
        elif line.startswith('|'):
            rows = []
            while index < len(lines) and lines[index].strip().startswith('|'):
                cells = [c.strip() for c in lines[index].strip().strip('|').split('|')]
                if not all(re.fullmatch(r'[:\- ]+', c) for c in cells):
                    rows.append(cells)
                index += 1
            out.append('<div class="manual-table-wrap"><table><thead><tr>' + ''.join('<th>' + inline(c) + '</th>' for c in rows[0]) + '</tr></thead><tbody>')
            out.extend('<tr>' + ''.join('<td>' + inline(c) + '</td>' for c in row) + '</tr>' for row in rows[1:])
            out.append('</tbody></table></div>')
            continue
        elif re.match(r'\d+\. ', line):
            out.append('<ol>')
            while index < len(lines) and re.match(r'\d+\. ', lines[index].strip()):
                out.append('<li>' + inline(re.sub(r'^\d+\. ', '', lines[index].strip())) + '</li>')
                index += 1
            out.append('</ol>')
            continue
        else:
            paragraph = [line]
            while index + 1 < len(lines) and lines[index+1].strip() and not re.match(r'#{2,3} |\||\d+\. ', lines[index+1].strip()):
                index += 1
                paragraph.append(lines[index].strip())
            out.append('<p>' + inline(' '.join(paragraph)) + '</p>')
        index += 1
    if section_open:
        out.append('</section>')
    document = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>工作台使用说明 V0.1 初稿 · EcoBag</title><link rel="icon" href="data:,"><link rel="stylesheet" href="/style.css"><script src="/manual.js" defer></script></head>
<body class="manual-page"><main class="manual-document"><header class="manual-header"><div><div class="eyebrow">ECOBAG / V0.1 初稿</div><h1>工作台手册</h1><p>订单工作台使用说明 · 从导入到审批、下单与到货</p></div><a href="/">返回工作台</a></header>
<nav class="manual-toc" aria-label="手册目录">''' + ''.join(toc) + '</nav>' + '\n'.join(out) + '<footer class="manual-footer">V0.1 初稿 · 2026年11月4日 · 本机测试版配套使用说明</footer></main></body></html>\n'
    (ROOT / 'manual.html').write_text(document, encoding='utf-8')
    print(f'Generated manual.html: {len(toc)} sections')


if __name__ == '__main__':
    build()
