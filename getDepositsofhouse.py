import io
import os
import re
import time
import json
import traceback
from datetime import datetime
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"
START_YEAR = int(os.getenv("PBOC_START_YEAR", "2015"))
END_YEAR = int(os.getenv("PBOC_END_YEAR", str(datetime.today().year)))
TARGET_TABLE_NAME = "金融机构人民币信贷收支表"
TARGET_ROW_KEYWORDS = ["住户存款"]
OUTPUT_CSV = os.getenv("PBOC_OUTPUT_CSV", "pboc_household_deposits.csv")
DOWNLOAD_DIR = os.getenv("PBOC_DOWNLOAD_DIR", "pboc_xls_cache")
DOWNLOAD_SLEEP_SECONDS = float(os.getenv("PBOC_DOWNLOAD_SLEEP_SECONDS", "1"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    )
}

def detect_month_from_header_text(text: str):
    """
    从表头文本里识别月份
    支持:
    1月 / 01月 / 2025.01 / 2025-01 / 202501 / Jan
    """
    if not text:
        return None

    t = normalize_text(text)

    # 先匹配 1月 / 01月
    m = re.search(r"(?<!\d)(1[0-2]|0?[1-9])月", t)
    if m:
        return int(m.group(1))

    # 再匹配 2025.01 / 2025-01 / 2025/01
    m = re.search(r"20\d{2}[-./](1[0-2]|0?[1-9])", t)
    if m:
        return int(m.group(1))

    # 再匹配 202501
    m = re.search(r"20\d{2}(1[0-2]|0[1-9])", t)
    if m:
        return int(m.group(1))

    return None

def find_month_columns(df: pd.DataFrame, target_row_index: int):
    """
    根据住户存款行上方的几行表头，识别哪些列对应哪个月份
    返回:
    {
        col_index: month
    }
    """
    month_cols = {}

    # 取目标行上方最多 5 行作为表头区域
    header_start = max(0, target_row_index - 5)
    header_end = target_row_index

    for col in range(df.shape[1]):
        header_parts = []
        for r in range(header_start, header_end):
            val = df.iat[r, col]
            if pd.notna(val):
                header_parts.append(str(val))

        header_text = normalize_text(" ".join(header_parts))
        month = detect_month_from_header_text(header_text)
        if month is not None:
            month_cols[col] = month

    return month_cols
def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def get_soup(url: str) -> BeautifulSoup:
    html = fetch_html(url)
    return BeautifulSoup(html, "html.parser")


def normalize_text(text: str) -> str:
    if text is None:
        return ""
    text = str(text).replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"\s+", "", text)
    return text.strip()


def ensure_dir(path: str):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def find_year_category_links():
    """
    从总入口页中找到：
    {year: category_page_url}
    """
    soup = get_soup(BASE_URL)
    links = soup.find_all("a", href=True)

    result = {}

    # 先找出每个年份对应的“金融机构信贷收支统计”链接
    for a in links:
        text = normalize_text(a.get_text())
        href = a["href"]

        if text == "金融机构信贷收支统计":
            full_url = urljoin(BASE_URL, href)

            # 尝试从 URL 或附近文本里识别年份
            # 这里利用页面结构：总页里每个年份下面都会紧跟一个“金融机构信贷收支统计”
            # 所以我们从父节点上下文找最近的年份文字
            parent_text = normalize_text(a.parent.get_text(" ", strip=True))
            whole_text = normalize_text(a.find_parent().get_text(" ", strip=True)) if a.find_parent() else ""
            context = parent_text + whole_text

            found_years = re.findall(r"(20\d{2})年统计数据", context)
            if found_years:
                year = int(found_years[0])
                if START_YEAR <= year <= END_YEAR:
                    result[year] = full_url

    # 如果上面的上下文法不稳，再走一遍更稳妥的方法：按页面中 a 标签顺序扫描
    if len(result) < (END_YEAR - START_YEAR + 1) // 2:
        result = {}
        current_year = None
        for a in links:
            text = normalize_text(a.get_text())
            href = a["href"]

            year_match = re.fullmatch(r"(20\d{2})年统计数据", text)
            if year_match:
                current_year = int(year_match.group(1))
                continue

            if text == "金融机构信贷收支统计" and current_year is not None:
                if START_YEAR <= current_year <= END_YEAR:
                    result[current_year] = urljoin(BASE_URL, href)

    return dict(sorted(result.items()))


def find_target_xls_url(category_url: str):
    """
    在“金融机构信贷收支统计”页中找到“金融机构人民币信贷收支表”的 xls 链接
    """
    soup = get_soup(category_url)

    # 页面一般是：标题文字 -> xls 链接
    text_nodes = soup.find_all(text=True)

    target_block = None
    for node in text_nodes:
        if TARGET_TABLE_NAME in str(node):
            parent = node.parent
            if parent:
                target_block = parent
                break

    if target_block is None:
        # 退化策略：直接扫所有文本附近的链接
        all_text = soup.get_text("\n", strip=True)
        if TARGET_TABLE_NAME not in all_text:
            raise ValueError(f"未找到目标表名: {TARGET_TABLE_NAME}")

    # 直接从所有 a 中找最靠近 TARGET_TABLE_NAME 的 xls
    all_links = soup.find_all("a", href=True)
    candidates = []

    for a in all_links:
        link_text = normalize_text(a.get_text())
        href = a["href"]
        full_url = urljoin(category_url, href)

        if link_text.lower() == "xls":
            candidates.append((a, full_url))

    # 借助页面文本顺序来判断哪个 xls 属于目标表
    page_text = soup.get_text("\n", strip=True)
    if TARGET_TABLE_NAME not in page_text:
        raise ValueError(f"页面中未找到: {TARGET_TABLE_NAME}")

    # 更稳的办法：读取 html，正则匹配“金融机构人民币信贷收支表”之后最近的 xls href
    html = fetch_html(category_url)
    pattern = re.compile(
        re.escape(TARGET_TABLE_NAME) + r".{0,800}?href=\"([^\"]+)\"[^>]*>\s*xls\s*<",
        re.IGNORECASE | re.DOTALL
    )
    m = pattern.search(html)
    if m:
        return urljoin(category_url, m.group(1))

    # 再退化
    if candidates:
        return candidates[0][1]

    raise ValueError("未找到 xls 链接")


def download_file(url: str, filepath: str):
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    with open(filepath, "wb") as f:
        f.write(resp.content)


def try_read_excel(filepath: str):
    """
    尝试多种方式读取 xls/xlsx
    """
    errors = []

    for engine in [None, "xlrd", "openpyxl"]:
        try:
            xls = pd.ExcelFile(filepath, engine=engine)
            sheets = {}
            for sheet_name in xls.sheet_names:
                sheets[sheet_name] = pd.read_excel(filepath, sheet_name=sheet_name, header=None, engine=engine)
            return sheets
        except Exception as e:
            errors.append(f"engine={engine}: {e}")

    raise RuntimeError("Excel 读取失败: " + " | ".join(errors))


def extract_household_deposit_from_df(df: pd.DataFrame, fallback_year: int):
    """
    在单个 sheet 里找“住户存款”，并拆出每个月的值
    返回 list[dict]
    """
    if df is None or df.empty:
        return []

    sdf = df.copy().fillna("")
    sdf = sdf.astype(str)

    for i in range(len(sdf)):
        row_values = [normalize_text(x) for x in sdf.iloc[i].tolist()]
        row_text = "|".join(row_values)

        if any(keyword in row_text for keyword in TARGET_ROW_KEYWORDS):
            month_cols = find_month_columns(df, i)

            records = []
            for col_idx, month in month_cols.items():
                raw = str(df.iat[i, col_idx]).strip().replace(",", "")
                if re.fullmatch(r"-?\d+(\.\d+)?", raw):
                    records.append({
                        "year": fallback_year,
                        "month": month,
                        "household_deposits": float(raw),
                        "row_index": i,
                        "col_index": col_idx,
                        "matched_row": str(df.iloc[i].tolist())
                    })

            # 按 month 排序
            records = sorted(records, key=lambda x: x["month"])

            if records:
                return records

    return []

def extract_household_deposit(filepath: str, fallback_year: int):
    sheets = try_read_excel(filepath)

    for sheet_name, df in sheets.items():
        results = extract_household_deposit_from_df(df, fallback_year=fallback_year)
        if results:
            for item in results:
                item["sheet_name"] = sheet_name
            return results

    return []

def infer_period_from_url_or_filename(text: str, fallback_year: int):
    """
    从 url 或文件名里尽量识别年月；如果失败，至少保留年份
    """
    # 常见是 2025111810564114123.xls 这种，不带月份含义
    # 因此默认使用年份 + None 月份
    return fallback_year, None


def main():
    ensure_dir(DOWNLOAD_DIR)

    year_links = find_year_category_links()
    print("找到年份页：")
    print(json.dumps(year_links, ensure_ascii=False, indent=2))

    records = []

    for year, category_url in year_links.items():
        try:
            print(f"\n处理 {year} -> {category_url}")
            xls_url = find_target_xls_url(category_url)
            print(f"  xls: {xls_url}")

            filename = f"{year}_{os.path.basename(xls_url.split('?')[0])}"
            filepath = os.path.join(DOWNLOAD_DIR, filename)

            # 1. 文件不存在才下载
            if not os.path.exists(filepath):
                download_file(xls_url, filepath)
                time.sleep(DOWNLOAD_SLEEP_SECONDS)

            # 2. 无论文件是否已存在，都要解析
            monthly_results = extract_household_deposit(filepath, fallback_year=year)

            if not monthly_results:
                print(f"  未找到“住户存款”月度数据: {filepath}")
                records.append({
                    "year": year,
                    "month": None,
                    "date": None,
                    "household_deposits": None,
                    "source_url": xls_url,
                    "source_file": filepath,
                    "status": "NOT_FOUND"
                })
                continue

            for item in monthly_results:
                y = item["year"]
                m = item["month"]
                date_str = f"{y}-{m:02d}-01"

                records.append({
                    "year": y,
                    "month": m,
                    "date": date_str,
                    "household_deposits": item["household_deposits"],
                    "sheet_name": item.get("sheet_name"),
                    "row_index": item.get("row_index"),
                    "col_index": item.get("col_index"),
                    "matched_row": item.get("matched_row"),
                    "source_url": xls_url,
                    "source_file": filepath,
                    "status": "OK"
                })

            print(f"  提取到 {len(monthly_results)} 个月份数据")

        except Exception as e:
            print(f"  失败: {year}, error={e}")
            traceback.print_exc()
            records.append({
                "year": year,
                "month": None,
                "date": None,
                "household_deposits": None,
                "source_url": category_url,
                "source_file": None,
                "status": f"ERROR: {e}"
            })

    out = pd.DataFrame(records)
    out = out.sort_values(["year", "month"], na_position="last").reset_index(drop=True)
    out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n完成，输出: {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
