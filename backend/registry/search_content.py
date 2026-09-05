import copy
import logging
import os
import re
from typing import List

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# ----------------------------------------------------------------------
# HTML extraction helpers
# ----------------------------------------------------------------------
def _extract_meta(soup: BeautifulSoup) -> dict:
    """Pull meta description and keywords if present."""
    description = ""
    keywords = ""
    desc_tag = soup.find("meta", attrs={"name": re.compile("description", re.I)})
    if desc_tag and desc_tag.get("content"):
        description = desc_tag["content"].strip()
    kw_tag = soup.find("meta", attrs={"name": re.compile("keywords", re.I)})
    if kw_tag and kw_tag.get("content"):
        keywords = kw_tag["content"].strip()
    return {"description": description, "keywords": keywords}

def _extract_lists(soup: BeautifulSoup) -> List[List[str]]:
    """Return a list of lists, each inner list representing a <ul>/<ol>."""
    all_lists = []
    for lst in soup.find_all(["ul", "ol"]):
        items = [li.get_text(separator=" ", strip=True) for li in lst.find_all("li")]
        if items:
            all_lists.append(items)
    return all_lists

def _extract_tables(soup: BeautifulSoup) -> List[List[List[str]]]:
    """Return a list of tables, each table is a list of rows, each row a list of cell texts."""
    tables_data = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["td", "th"])]
            if cells:
                rows.append(cells)
        if rows:
            tables_data.append(rows)
    return tables_data

def _extract_code_blocks(soup: BeautifulSoup) -> List[str]:
    """Collect text from <pre> and <code> blocks."""
    blocks = []
    for tag in soup.find_all(["pre", "code"]):
        txt = tag.get_text(separator=" ", strip=True)
        if txt:
            blocks.append(txt)
    return blocks

def _empty_result(url: str, error: str = "") -> dict:
    return {
        "url": url,
        "title": "",
        "content": "",
        "lists": [],
        "tables": [],
        "code_blocks": [],
        "meta_description": "",
        "meta_keywords": "",
        "success": False,
        "error": error,
    }

from urllib.parse import urljoin
from registry.search_security import is_safe_url

_MAX_PAGE_BYTES = 2_000_000
_MAX_REDIRECTS = 5

def fetch_webpage_content(url: str, timeout: int = 8, max_bytes: int = _MAX_PAGE_BYTES, max_redirects: int = _MAX_REDIRECTS) -> dict:
    """Fetch and extract meaningful content from a webpage safely with SSRF protection across all redirects."""
    current_url = url
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    res = None
    raw_bytes = bytearray()
    encoding = "utf-8"
    content_type = ""

    for hop in range(max_redirects + 1):
        if not is_safe_url(current_url):
            logger.warning(f"Fetch webpage bloccato da SSRF protection (hop {hop}): {current_url}")
            return _empty_result(current_url, "Blocked by SSRF policy")

        try:
            res = requests.get(current_url, headers=headers, timeout=timeout, allow_redirects=False, stream=True)
            if res.status_code in (301, 302, 303, 307, 308):
                location = res.headers.get("Location")
                res.close()
                if not location:
                    return _empty_result(current_url, "Redirect missing Location header")
                current_url = urljoin(current_url, location)
                continue

            if res.status_code >= 400:
                status = res.status_code
                res.close()
                return _empty_result(current_url, f"HTTP {status}")

            for chunk in res.iter_content(chunk_size=16384):
                raw_bytes.extend(chunk)
                if len(raw_bytes) > max_bytes:
                    logger.info(f"Dimensione pagina eccede {max_bytes} bytes per {current_url}, contenuto troncato.")
                    break

            encoding = res.encoding or "utf-8"
            content_type = res.headers.get("Content-Type", "").lower()
            res.close()
            break
        except requests.Timeout:
            if res:
                res.close()
            return _empty_result(current_url, "Timeout")
        except Exception as e:
            if res:
                res.close()
            logger.warning(f"Errore connessione HTTP fetch per {current_url}: {e}")
            return _empty_result(current_url, "Connection error")
    else:
        return _empty_result(current_url, "Too many redirects")

    text_content = raw_bytes.decode(encoding, errors="replace")

    # Handle plain text / json
    is_html = "html" in content_type
    is_json = "json" in content_type
    url_path = current_url.lower().split("?", 1)[0].split("#", 1)[0]
    looks_like_text = url_path.endswith((".md", ".txt", ".json"))

    if not is_html and (content_type.startswith("text/") or is_json or looks_like_text):
        text_body = text_content.strip()
        return {
            "url": current_url,
            "title": os.path.basename(url_path) or current_url,
            "content": text_body,
            "lists": [],
            "tables": [],
            "code_blocks": [],
            "meta_description": "",
            "meta_keywords": "",
            "success": bool(text_body),
            "error": "" if text_body else "Empty response body",
        }

    # HTML handling
    try:
        soup = BeautifulSoup(text_content, "html.parser")
    except Exception as e:
        return _empty_result(current_url, "ParseError: HTML parsing failed")

    title_tag = soup.find("title")
    title_text = title_tag.get_text(strip=True) if title_tag else ""
    meta_info = _extract_meta(soup)

    main_content = ""
    content_areas = soup.find_all(
        ["main", "article", "section", "div"],
        class_=re.compile("content|main|body|article|post|entry|text", re.I),
    )
    if content_areas:
        for area in content_areas[:3]:
            main_content += area.get_text(separator=" ", strip=True) + " "
    main_content = re.sub(r"\s+", " ", main_content).strip()

    if len(main_content) < 600:
        body = soup.find("body")
        if body:
            body_copy = copy.copy(body)
            for noise in body_copy.find_all(["script", "style", "noscript", "template", "nav", "header", "footer", "aside", "svg"]):
                noise.extract()
            body_text = re.sub(r"\s+", " ", body_copy.get_text(separator=" ", strip=True)).strip()
            if len(body_text) > len(main_content):
                main_content = body_text

    result = {
        "url": current_url,
        "title": title_text,
        "content": main_content,
        "lists": _extract_lists(soup),
        "tables": _extract_tables(soup),
        "code_blocks": _extract_code_blocks(soup),
        "meta_description": meta_info.get("description", ""),
        "meta_keywords": meta_info.get("keywords", ""),
        "success": True,
        "error": "",
    }
    return result

# ----------------------------------------------------------------------
# Content summarization helpers
# ----------------------------------------------------------------------
def extract_key_points(text: str) -> List[str]:
    points: List[str] = []
    bullet_pat = re.compile(r"^\s*[-*•]\s+(.*)")
    numbered_pat = re.compile(r"^\s*\d+[\.\)]\s+(.*)")
    for line in text.splitlines():
        m = bullet_pat.match(line) or numbered_pat.match(line)
        if m:
            points.append(m.group(1).strip())
    return points[:8]

def get_tldr(text: str, max_sentences: int = 3) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    selected = [s.strip() for s in sentences if s][:max_sentences]
    return " ".join(selected)
