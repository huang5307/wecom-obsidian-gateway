from services.wechat_cleaner import parse_wechat_to_markdown
import lxml.html
import re
import time
import logging
import asyncio
import httpx
import trafilatura
from core.storage.base import BaseStorage

logger = logging.getLogger("services.url_archiver")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
        "MicroMessenger/8.0.40 NetType/WIFI Language/zh_CN"
    )
}

URL_REGEX = re.compile(r"https?://[^\s<>\"'()]+")

def extract_first_url(text: str) -> tuple[str | None, str]:
    match = URL_REGEX.search(text)
    if not match:
        return None, text
    url = match.group(0)
    remaining_text = (text[:match.start()] + " " + text[match.end():]).strip()
    remaining_text = re.sub(r"\s+", " ", remaining_text).strip()
    return url, remaining_text

async def _download_and_store_image(http_client: httpx.AsyncClient, img_url: str, page_url: str,
                                   safe_title: str, index: int, storage: BaseStorage) -> tuple[str | None, str | None]:
    try:
        headers = {
            "User-Agent": DEFAULT_HEADERS["User-Agent"],
            "Referer": page_url
        }
        resp = await http_client.get(img_url, headers=headers, timeout=15.0)
        if resp.status_code != 200:
            return None, None

        content_type = resp.headers.get("content-type", "").lower()
        ext = "jpg"
        if "png" in content_type or "wx_fmt=png" in img_url:
            ext = "png"
        elif "webp" in content_type or "wx_fmt=webp" in img_url:
            ext = "webp"
        elif "gif" in content_type or "wx_fmt=gif" in img_url:
            ext = "gif"
        elif "jpeg" in content_type or "jpg" in content_type:
            ext = "jpg"

        img_filename = f"{safe_title}_{index:02d}.{ext}"

        loop = asyncio.get_running_loop()
        saved_name = await loop.run_in_executor(
            None,
            lambda: storage.save_attachment(img_filename, resp.content, content_type)
        )
        return img_url, saved_name
    except Exception as e:
        logger.warning(f"转存图片异常: {e} - {img_url}")
        return None, None


def _extract_html_title(html_content: str) -> str:
    import html as html_module
    # 1. og:title（覆盖微信文章、主流媒体与各大网站）
    for m in re.finditer(r'<meta[^>]+content="([^"]+)"', html_content, re.IGNORECASE):
        tag = m.group(0)
        if 'property="og:title"' in tag or "property='og:title'" in tag:
            t = html_module.unescape(m.group(1)).strip()
            if t and "参数错误" not in t:
                return t

    # 2. 微信正文 h1 标题
    m = re.search(r'<h1[^>]*id="activity-name"[^>]*>(.*?)</h1>', html_content, re.DOTALL | re.IGNORECASE)
    if m:
        t = html_module.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip()
        if t:
            return t

    # 3. 通用 HTML title 标签（覆盖 GitHub、文档等通用网页）
    m = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.DOTALL | re.IGNORECASE)
    if m:
        t = html_module.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip()
        if t and "参数错误" not in t:
            return t

    return ""


def _clean_wechat_html(html: str, url: str) -> str:
    if "mp.weixin.qq.com" not in url and 'id="js_content"' not in html:
        return html
    try:
        doc = lxml.html.fromstring(html)
        js = doc.xpath('//div[@id="js_content"]')
        if not js:
            return html
        node = js[0]
        for bad in node.xpath('.//script | .//style'):
            bad.drop_tree()
        for bad in node.xpath('.//*[contains(text(), "在小说阅读器") or contains(text(), "沉浸阅读")]'):
            bad.drop_tree()
        for img in node.xpath('.//img'):
            src = img.get('data-src') or img.get('src')
            if src and src.startswith('http'):
                img.set('src', src)
                if 'data-src' in img.attrib:
                    del img.attrib['data-src']
        return f"<html><body>{lxml.html.tostring(node, encoding='utf-8').decode('utf-8')}</body></html>"
    except Exception:
        return html

async def fetch_url_to_markdown(url: str, fallback_title: str = "", storage: BaseStorage = None, r2_adapter=None, **kwargs) -> dict:
    storage = storage or r2_adapter
    html_content = ""
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                html_content = resp.text
    except Exception as e:
        logger.error(f"抓取网页正文失败: {e} - {url}")

    archive_time = time.strftime("%Y-%m-%d %H:%M:%S")

    if not html_content:
        title = fallback_title or "未命名网页"
        md_text = (
            f"---\n"
            f"title: \"{title}\"\n"
            f"url: \"{url}\"\n"
            f"created: {archive_time}\n"
            f"source: wechat\n"
            f"tags:\n"
            f"  - clipping\n"
            f"---\n\n"
            f"# {title}\n\n"
            f"正文抓取超时，请访问原文：\n\n[{title}]({url})\n"
        )
        return {"title": title, "markdown": md_text, "url": url}

        # 微信公众号优先使用原生高保真提取器
    is_wx, wx_md = parse_wechat_to_markdown(html_content)
    if is_wx and wx_md:
        extracted_text = wx_md
    else:
        extracted_text = trafilatura.extract(_clean_wechat_html(html_content, url),
        output_format="markdown",
        include_links=True,
        include_images=True,
        favor_recall=True
        )
    metadata = trafilatura.extract_metadata(html_content)

    final_title = ""
    if metadata and metadata.title:
        final_title = metadata.title.strip()
    if not final_title:
        final_title = fallback_title or "未命名网页"

    body_text = extracted_text if extracted_text else "（未能提取到正文文本）"
    safe_title = re.sub(r'[\r\n\t\\/:*?"<>| ]+', '_', final_title).strip('_') or "网页归档"

    if storage:
        img_matches = list(re.finditer(r"!\[(.*?)\]\((https?://[^)\s]+)\)", body_text))
        if img_matches:
            target_matches = img_matches[:25]
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as http_client:
                tasks = [
                    _download_and_store_image(http_client, m.group(2), url, safe_title, idx + 1, storage)
                    for idx, m in enumerate(target_matches)
                ]
                results = await asyncio.gather(*tasks)

            for old_url, new_filename in results:
                if old_url and new_filename:
                    escaped_url = re.escape(old_url)
                    body_text = re.sub(rf"!\[(.*?)\]\({escaped_url}\)", rf"![[{new_filename}]]", body_text)

    safe_yaml_title = final_title.replace('"', '\\"')
    frontmatter = (
        f"---\n"
        f"title: \"{safe_yaml_title}\"\n"
        f"url: \"{url}\"\n"
        f"created: {archive_time}\n"
        f"source: wechat\n"
        f"tags:\n"
        f"  - clipping\n"
        f"---\n\n"
        f"# {final_title}\n\n"
    )
    return {
        "title": final_title,
        "markdown": frontmatter + body_text,
        "url": url
    }
