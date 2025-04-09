import requests
import json
import pandas as pd
import re
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import dateparser
import time
import random
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright

# ========== 全局变量控制输出路径前缀 ==========
FILE_PREFIX = "default"

def set_file_prefix(prefix: str):
    global FILE_PREFIX
    FILE_PREFIX = prefix
    Path(f"screenshots_{FILE_PREFIX}").mkdir(parents=True, exist_ok=True)
    Path(f"output_{FILE_PREFIX}").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=f"output_{FILE_PREFIX}/failed_urls.log",
        level=logging.WARNING,
        format="%(asctime)s - %(message)s"
    )

# ========== Cookie 注入相关 ==========
def load_session_cookies(domain_keyword):
    cookie_file_map = {
        "linkedin.com": "linkedin_cookies.json",
        "facebook.com": "facebook_cookies.json",
        "instagram.com": "instagram_cookies.json",
        "x.com": "twitter_cookies.json",
        "twitter.com": "twitter_cookies.json"
    }
    for key, file in cookie_file_map.items():
        if key in domain_keyword:
            path = Path(file)
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except:
                    pass
    return []

def inject_cookies_if_needed(context, url):
    cookies = load_session_cookies(url)
    if cookies:
        try:
            context.add_cookies(cookies)
        except:
            pass

# ========== 截图路径生成器 ==========
def get_screenshot_path(url):
    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', url)[:50]
    return f"screenshots_{FILE_PREFIX}/{safe_name}.png"

# ========== Excel 辅助类 ==========
class ExcelWriterHelper:
    MAX_CELL_LENGTH = 32767

    @staticmethod
    def clean_text(text):
        if not text:
            return ""
        return str(text).strip().replace("\u200b", "").replace("\u200e", "")

    @staticmethod
    def truncate_text(text):
        if not text:
            return ""
        return text if len(text) <= ExcelWriterHelper.MAX_CELL_LENGTH else text[:ExcelWriterHelper.MAX_CELL_LENGTH] + " [已截断]"

    @staticmethod
    def escape_excel_formula(text):
        if isinstance(text, str) and text.startswith(("=", "+", "-", "@")):
            return "'" + text
        return text

    @classmethod
    def preprocess_record(cls, record: dict) -> dict:
        return {
            k: cls.escape_excel_formula(cls.truncate_text(cls.clean_text(v)))
            for k, v in record.items()
        }

    @classmethod
    def write_to_excel(cls, records: list, filename: str):
        df = pd.DataFrame([cls.preprocess_record(r) for r in records])
        df.fillna("", inplace=True)
        df.to_excel(filename, index=False)
        print(f"✅ Excel 已保存：{filename}")

# ========== 发布时间提取 ==========
def extract_publish_date_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    # 1. ✅ meta 标签匹配
    meta_selectors = [
        {'name': 'pubdate'}, {'name': 'publishdate'}, {'name': 'date'},
        {'name': 'dc.date.issued'}, {'property': 'article:published_time'},
        {'property': 'og:pubdate'}, {'itemprop': 'datePublished'}
    ]
    for selector in meta_selectors:
        meta_tag = soup.find("meta", attrs=selector)
        if meta_tag and meta_tag.get("content"):
            parsed = dateparser.parse(meta_tag["content"])
            if parsed:
                return parsed.isoformat()

    # 2. ✅ time 标签的 datetime 属性
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        parsed = dateparser.parse(time_tag["datetime"])
        if parsed:
            return parsed.isoformat()

    # 3. ✅ 结构型 fallback：带 published 的 div/span 等
    for tag in soup.find_all(["div", "span", "p"], class_=re.compile(r"(date|meta|info|time)", re.I)):
        text = tag.get_text(separator=" ", strip=True)
        if "published" in text.lower():
            # 例如 Published: Dec 21, 2022 10:00 AM SGT
            date_match = re.search(r"(?:published\\W*)?(\\w+ \\d{1,2}, \\d{4}[^\\n]*)", text, re.I)
            if date_match:
                parsed = dateparser.parse(date_match.group(1))
                if parsed:
                    return parsed.isoformat()

    return None

# ========== 其他辅助信息提取 ==========
def extract_author(soup):
    meta = soup.find("meta", attrs={"name": "author"})
    if meta and meta.get("content"):
        return meta["content"].strip()
    return None

def extract_title(soup):
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"].strip()
    if soup.title:
        return soup.title.get_text(strip=True)
    return None

def detect_failure_reason(html: str, title: str, content: str) -> str:
    if not html:
        return "no response"
    if "cloudflare" in html.lower() or "captcha" in html.lower():
        return "blocked by Cloudflare / captcha"
    if title and re.search(r"404|not found|page not found", title, re.I):
        return "404 / page not found"
    if content and len(content) < 100:
        return "very short content"
    if content and "enable javascript" in content.lower():
        return "JS required / unsupported browser"
    if not content:
        return "no content"
    return "ok"

# ========== 核心抓取逻辑（requests + playwright） ==========
def enhanced_fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com"
    }
    try:
        time.sleep(random.uniform(1, 3))
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return r.text, None
    except:
        pass

    with sync_playwright() as p:
        browser = None
        page = None
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            inject_cookies_if_needed(context, url)
            page = context.new_page()
            page.goto(url, timeout=30000)
            page.wait_for_load_state("networkidle")
            content = page.content()
            return content, None
        except Exception as e:
            screenshot_path = get_screenshot_path(url)
            if page:
                try:
                    page.screenshot(path=screenshot_path)
                    logging.warning(f"截图已保存：{screenshot_path} | URL: {url}")
                    return None, screenshot_path
                except:
                    pass
            logging.warning(f"Playwright失败：{url} - {e}")
            return None, None
        finally:
            if browser:
                browser.close()

# ========== 新闻页内容抓取统一接口 ==========
def extract_news_content(url):
    html, screenshot_path = enhanced_fetch_html(url)
    has_screenshot = bool(screenshot_path)
    if not html:
        return {
            "url": url,
            "content": None,
            "publish_time": None,
            "title": None,
            "author": None,
            "scrape_time": datetime.now(timezone.utc).isoformat(),
            "method": "failed",
            "failed_reason": "no response",
            "screenshot": screenshot_path or "",
            "has_screenshot": has_screenshot
        }
    soup = BeautifulSoup(html, "html.parser")
    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
    full_text = "\n".join(paragraphs)
    title = extract_title(soup)
    failed_reason = detect_failure_reason(html, title, full_text)
    return {
        "url": url,
        "content": full_text,
        "publish_time": extract_publish_date_from_html(html),
        "title": title,
        "author": extract_author(soup),
        "scrape_time": datetime.now(timezone.utc).isoformat(),
        "method": "playwright" if "<html" in html and "</html>" in html else "requests",
        "failed_reason": failed_reason,
        "screenshot": screenshot_path or "",
        "has_screenshot": has_screenshot
    }

# ========== 批量抓取接口 ==========
def scrape_multiple_urls(url_list, output_prefix="default"):
    set_file_prefix(output_prefix)
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        for result in executor.map(extract_news_content, url_list):
            results.append(result)

    output_dir = Path(f"output_{FILE_PREFIX}")
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / f"{FILE_PREFIX}.json"
    excel_path = output_dir / f"{FILE_PREFIX}.xlsx"
    csv_path = output_dir / f"{FILE_PREFIX}.csv"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    ExcelWriterHelper.write_to_excel(results, str(excel_path))
    pd.DataFrame(results).to_csv(csv_path, index=False, encoding="utf-8-sig")

    return results

# ========== 从 Excel 文件读取 URL 并批量抓取 ==========
def scrape_from_excel(filepath: str, url_column: str = "url"):
    filename = Path(filepath).stem
    df = pd.read_excel(filepath)
    urls = df[url_column].dropna().tolist()
    scrape_multiple_urls(urls, output_prefix=filename)

