import re
import lxml.html

def parse_wechat_to_markdown(html: str) -> tuple[bool, str]:
    if 'id="js_content"' not in html:
        return False, ""
    try:
        doc = lxml.html.fromstring(html)
        js = doc.xpath('//div[@id="js_content"]')
        if not js:
            return False, ""
        node = js[0]

        # 剔除脚本、样式与微信小说推广组件
        for bad in node.xpath('.//script | .//style'):
            bad.drop_tree()
        for bad in node.xpath('.//*[contains(text(), "在小说阅读器") or contains(text(), "沉浸阅读")]'):
            bad.drop_tree()

        lines = []
        for el in node.iter():
            tag = el.tag.lower() if isinstance(el.tag, str) else ""
            if tag == 'img':
                src = el.get('data-src') or el.get('src') or ""
                if src.startswith('http'):
                    lines.append(f"\n\n![配图]({src})\n\n")
            elif tag in ('p', 'section', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br'):
                t = el.text.strip() if el.text else ""
                if t:
                    if tag.startswith('h'):
                        level = tag[1]
                        lines.append(f"\n\n{'#' * int(level)} {t}\n\n")
                    else:
                        lines.append(f"\n\n{t}\n\n")
            else:
                t = el.text.strip() if el.text else ""
                if t:
                    lines.append(t)

        raw_md = "".join(lines)
        clean_md = re.sub(r'\n{3,}', '\n\n', raw_md).strip()
        return True, clean_md
    except Exception:
        return False, ""
