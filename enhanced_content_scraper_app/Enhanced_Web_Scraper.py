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

def setup_logging(prefix: str):
    log_dir = Path(f"output_{prefix}")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "scraper.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    logging.info(f"🟢 日志系统已初始化。日志文件路径：{log_path}")

def set_file_prefix(prefix: str):
    global FILE_PREFIX
    FILE_PREFIX = prefix
    Path(f"screenshots_{FILE_PREFIX}").mkdir(parents=True, exist_ok=True)
    Path(f"output_{FILE_PREFIX}").mkdir(parents=True, exist_ok=True)
    setup_logging(prefix)

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
        if pd.isna(text):
            return ""
        text = str(text)
        text = re.sub(r"[\x00-\x1F\x7F]", "", text)
        text = text.strip().replace("\u200b", "").replace("\u200e", "")
        return text

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
        processed = {}
        for k, v in record.items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            v = cls.clean_text(v)
            v = cls.truncate_text(v)
            v = cls.escape_excel_formula(v)
            processed[k] = v
        return processed

    @classmethod
    def write_all_outputs(cls, records: list, prefix: str):
        if not records:
            print("⚠️ 无数据可写入。")
            return

        output_dir = Path(f"output_{prefix}")
        output_dir.mkdir(parents=True, exist_ok=True)

        json_path = output_dir / f"{prefix}.json"
        excel_path = output_dir / f"{prefix}.xlsx"
        csv_path = output_dir / f"{prefix}.csv"

        all_keys = set(k for r in records for k in r.keys())
        standardized_records = [{k: r.get(k, "") for k in all_keys} for r in records]

        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(standardized_records, f, ensure_ascii=False, indent=2)
            logging.info(f"✅ JSON 已保存：{json_path}")
        except Exception as e:
            logging.exception(f"❌ 写入 JSON 失败：{e}")

        try:
            df = pd.DataFrame([cls.preprocess_record(r) for r in standardized_records])
            df.fillna("", inplace=True)
            df.to_excel(excel_path, index=False)
            logging.info(f"✅ Excel 已保存：{excel_path}")
        except Exception as e:
            logging.exception(f"❌ 写入 Excel 失败：{e}")

        try:
            pd.DataFrame(standardized_records).to_csv(csv_path, index=False, encoding="utf-8-sig")
            logging.info(f"✅ CSV 已保存：{csv_path}")
        except Exception as e:
            logging.exception(f"❌ 写入 CSV 失败：{e}")

# ========== 发布时间提取 ==========
def extract_publish_date_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
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

    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        parsed = dateparser.parse(time_tag["datetime"])
        if parsed:
            return parsed.isoformat()

    for tag in soup.find_all(["div", "span", "p"], class_=re.compile(r"(date|meta|info|time)", re.I)):
        text = tag.get_text(separator=" ", strip=True)
        if "published" in text.lower():
            date_match = re.search(r"(?:published\\W*)?(\\w+ \\d{1,2}, \\d{4}[^\\n]*)", text, re.I)
            if date_match:
                parsed = dateparser.parse(date_match.group(1))
                if parsed:
                    return parsed.isoformat()

    return None

# ========== 内容辅助提取 ==========
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

# ========== 网页内容抓取 ==========
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

# ========== 提取页面内容 ==========
def extract_news_content(url):
    logging.info(f"开始抓取: {url}")
    html, screenshot_path = enhanced_fetch_html(url)
    has_screenshot = bool(screenshot_path)
    if not html:
        logging.warning(f"❌ 抓取失败: {url} | 截图: {screenshot_path}")
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
    method = "playwright" if "<html" in html and "</html>" in html else "requests"
    logging.info(f"✅ 抓取成功: {url} | 方法: {method}")
    return {
        "url": url,
        "content": full_text,
        "publish_time": extract_publish_date_from_html(html),
        "title": title,
        "author": extract_author(soup),
        "scrape_time": datetime.now(timezone.utc).isoformat(),
        "method": method,
        "failed_reason": failed_reason,
        "screenshot": screenshot_path or "",
        "has_screenshot": has_screenshot
    }

# ========== 批量抓取 ==========
def scrape_multiple_urls(url_list, output_prefix="default"):
    set_file_prefix(output_prefix)
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        for result in executor.map(extract_news_content, url_list):
            results.append(result)

    ExcelWriterHelper.write_all_outputs(results, FILE_PREFIX)
    logging.info(f"🟢 全部处理完成，共 {len(results)} 条记录。")
    return results

# ========== 从 Excel 文件读取 URL 并抓取 ==========
def scrape_from_excel(filepath: str, url_column: str = "url"):
    filename = Path(filepath).stem
    df = pd.read_excel(filepath)
    urls = df[url_column].dropna().tolist()
    scrape_multiple_urls(urls, output_prefix=filename)


