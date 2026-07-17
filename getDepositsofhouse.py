import os
import re
import time
import json
import traceback
from io import StringIO
from datetime import datetime
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"
START_YEAR = int(os.getenv("PBOC_START_YEAR", "2015"))
END_YEAR = int(os.getenv("PBOC_END_YEAR", str(datetime.today().year)))
DOWNLOAD_DIR = os.getenv("PBOC_DOWNLOAD_DIR", "pboc_xls_cache")
DOWNLOAD_SLEEP_SECONDS = float(os.getenv("PBOC_DOWNLOAD_SLEEP_SECONDS", "1"))

DEPOSIT_CATEGORY_NAME = "金融机构信贷收支统计"
DEPOSIT_TABLE_NAME = "金融机构人民币信贷收支表"
DEPOSIT_ROW_KEYWORDS = ["住户存款"]
DEPOSIT_OUTPUT_CSV = os.getenv("PBOC_OUTPUT_CSV", "pboc_household_deposits.csv")

MONEY_CATEGORY_NAME = "货币统计概览"
MONEY_TABLE_NAME = "货币供应量"
MONEY_OUTPUT_CSV = os.getenv("MONEY_SUPPLY_OUTPUT_CSV", "pboc_money_supply.csv")
MONEY_BASE_YEAR = int(os.getenv("MONEY_SUPPLY_BASE_YEAR", str(max(2014, START_YEAR - 1))))

SOCIAL_FINANCING_CATEGORY_NAME = "社会融资规模"
SOCIAL_FINANCING_TABLE_NAME = "社会融资规模增量统计表"
SOCIAL_FINANCING_OUTPUT_CSV = os.getenv("SOCIAL_FINANCING_OUTPUT_CSV", "pboc_social_financing_flow.csv")

PMI_OUTPUT_CSV = os.getenv("PMI_OUTPUT_CSV", "china_manufacturing_pmi.csv")
PMI_RELEASE_LIST_URL = os.getenv("PMI_RELEASE_LIST_URL", "https://www.stats.gov.cn/sj/zxfb/")
PMI_BOOTSTRAP_URL = os.getenv(
    "PMI_BOOTSTRAP_URL",
    "https://www.stats.gov.cn/sj/zxfb/202506/t20250630_1960283.html",
)
PMI_LOOKBACK_MONTHS = int(os.getenv("PMI_LOOKBACK_MONTHS", "24"))
PMI_RELEASE_LIST_PAGES = int(os.getenv("PMI_RELEASE_LIST_PAGES", "6"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    )
}


def normalize_text(text: str) -> str:
    if text is None:
        return ""
    text = str(text).replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"\s+", "", text)
    return text.strip()


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def get_soup(url: str) -> BeautifulSoup:
    return BeautifulSoup(fetch_html(url), "html.parser")


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def detect_month_from_header_text(text: str):
    """
    从表头文本里识别月份。
    PBoC Excel 里 2025.10 有时会被 pandas 读成 2025.1，后面 find_month_columns 会用重复月份保护逻辑修正。
    """
    if not text:
        return None

    normalized = normalize_text(text)

    match = re.search(r"(?<!\d)(1[0-2]|0?[1-9])月", normalized)
    if match:
        return int(match.group(1))

    match = re.search(r"20\d{2}[-./](1[0-2]|0?[1-9])", normalized)
    if match:
        return int(match.group(1))

    match = re.search(r"20\d{2}(1[0-2]|0[1-9])", normalized)
    if match:
        return int(match.group(1))

    return None


def find_month_columns(df: pd.DataFrame, target_row_index: int):
    month_cols = {}
    header_start = max(0, target_row_index - 6)
    header_end = target_row_index + 1

    for col in range(df.shape[1]):
        header_parts = []
        for row_index in range(header_start, header_end):
            value = df.iat[row_index, col]
            if pd.notna(value):
                header_parts.append(str(value))

        header_text = normalize_text(" ".join(header_parts))
        month = detect_month_from_header_text(header_text)
        if month is not None:
            month_cols[col] = month

    ordered_cols = sorted(month_cols)
    ordered_months = [month_cols[col] for col in ordered_cols]
    if ordered_months and len(set(ordered_months)) != len(ordered_months):
        # 央行表里 2025.10 可能被读成 2025.1，造成重复月份。
        # 月度表的列顺序固定为 1..12，所以遇到重复时按列顺序重建月份。
        for month_index, col in enumerate(ordered_cols, start=1):
            month_cols[col] = month_index

    return month_cols


def find_year_category_links(category_name: str, start_year: int, end_year: int):
    soup = get_soup(BASE_URL)
    result = {}
    current_year = None

    for anchor in soup.find_all("a", href=True):
        text = normalize_text(anchor.get_text())
        href = anchor["href"]

        year_match = re.fullmatch(r"(20\d{2})年统计数据", text)
        if year_match:
            current_year = int(year_match.group(1))
            continue

        if text == normalize_text(category_name) and current_year is not None:
            if start_year <= current_year <= end_year and current_year not in result:
                result[current_year] = urljoin(BASE_URL, href)

    return dict(sorted(result.items()))


def find_named_xls_url(category_url: str, table_name: str):
    html = fetch_html(category_url)
    normalized_table_name = normalize_text(table_name)

    pattern = re.compile(
        re.escape(table_name) + r".{0,1200}?href=\"([^\"]+\.(?:xls|xlsx))\"",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(html)
    if match:
        return urljoin(category_url, match.group(1))

    soup = BeautifulSoup(html, "html.parser")
    all_links = soup.find_all("a", href=True)

    for index, anchor in enumerate(all_links):
        link_text = normalize_text(anchor.get_text())
        if normalized_table_name not in link_text:
            continue

        for candidate in all_links[index:index + 10]:
            href = candidate["href"]
            if re.search(r"\.(xls|xlsx)(?:$|\?)", href, re.IGNORECASE):
                return urljoin(category_url, href)

    text_nodes = soup.find_all(string=True)
    for node in text_nodes:
        if normalized_table_name not in normalize_text(node):
            continue

        parent = node.parent
        while parent is not None:
            for candidate in parent.find_all("a", href=True):
                href = candidate["href"]
                if re.search(r"\.(xls|xlsx)(?:$|\?)", href, re.IGNORECASE):
                    return urljoin(category_url, href)
            parent = parent.parent

    raise ValueError(f"未找到 {table_name} 的 xls/xlsx 链接")


def download_file(url: str, filepath: str):
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    with open(filepath, "wb") as file:
        file.write(resp.content)


def try_read_excel(filepath: str):
    errors = []
    for engine in [None, "xlrd", "openpyxl"]:
        try:
            workbook = pd.ExcelFile(filepath, engine=engine)
            sheets = {}
            for sheet_name in workbook.sheet_names:
                sheets[sheet_name] = pd.read_excel(
                    filepath,
                    sheet_name=sheet_name,
                    header=None,
                    engine=engine,
                )
            return sheets
        except Exception as exc:
            errors.append(f"engine={engine}: {exc}")
    raise RuntimeError("Excel 读取失败: " + " | ".join(errors))


def parse_numeric_cell(value):
    if pd.isna(value):
        return None
    raw = str(value).strip().replace(",", "")
    if re.fullmatch(r"-?\d+(\.\d+)?", raw):
        return float(raw)
    return None


def parse_year_month_label(text: str):
    if text is None:
        return None

    raw = str(text).strip()
    raw = raw.replace("\u3000", " ").replace("\xa0", " ")
    match = re.search(r"(20\d{2})[年./-]\s*(1[0-2]|0?[1-9])月?", raw)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def iter_pmi_release_list_urls():
    yield PMI_RELEASE_LIST_URL

    if PMI_RELEASE_LIST_PAGES <= 1:
        return

    list_url = PMI_RELEASE_LIST_URL.split("#", 1)[0].split("?", 1)[0]
    if list_url.endswith("index.html"):
        base_url = list_url[: -len("index.html")]
    elif list_url.endswith("/"):
        base_url = list_url
    else:
        base_url = list_url + "/"

    for page_index in range(1, PMI_RELEASE_LIST_PAGES):
        yield urljoin(base_url, f"index_{page_index}.html")


def extract_household_deposit_from_df(df: pd.DataFrame, fallback_year: int):
    if df is None or df.empty:
        return []

    sdf = df.copy().fillna("").astype(str)
    for row_index in range(len(sdf)):
        row_values = [normalize_text(x) for x in sdf.iloc[row_index].tolist()]
        row_text = "|".join(row_values)

        if any(keyword in row_text for keyword in DEPOSIT_ROW_KEYWORDS):
            month_cols = find_month_columns(df, row_index)
            records = []

            for col_index, month in month_cols.items():
                numeric_value = parse_numeric_cell(df.iat[row_index, col_index])
                if numeric_value is None:
                    continue
                records.append({
                    "year": fallback_year,
                    "month": month,
                    "household_deposits": numeric_value,
                    "row_index": row_index,
                    "col_index": col_index,
                    "matched_row": str(df.iloc[row_index].tolist()),
                })
            records = sorted(records, key=lambda item: item["month"])
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


def detect_money_row_type(row_text: str):
    normalized = normalize_text(row_text)
    if "M2" in normalized and ("货币和准货币" in normalized or "Quasi-money" in normalized or "Money&Quasi-money" in normalized):
        return "m2_balance_yiyuan"
    if "M1" in normalized and "M2" not in normalized:
        return "m1_balance_yiyuan"
    return None


def extract_revised_m1_base_from_df(df: pd.DataFrame):
    """
    关键修正点：
    央行自 2025 年 1 月起启用新 M1 口径。
    2025 年货币供应量表的注释区提供了“按可比口径回溯后，2024 年各月末 M1 可比余额”。
    计算 2025 年 M1 同比时，必须用这里的 2024 可比余额做基数，不能用 2024 主表里的旧口径 M1。

    返回: {month: comparable_2024_m1_balance}
    """
    if df is None or df.empty:
        return {}

    sdf = df.copy().fillna("").astype(str)
    note_row = None
    for row_index in range(len(sdf)):
        row_text = normalize_text("|".join(sdf.iloc[row_index].tolist()))
        if "按可比口径回溯" in row_text and "2024年各月末M1" in row_text:
            note_row = row_index
            break

    if note_row is None:
        return {}

    month_cols = {}
    header_row = None
    search_end = min(len(sdf), note_row + 12)
    for row_index in range(note_row + 1, search_end):
        row_month_cols = {}
        for col_index in range(df.shape[1]):
            value = df.iat[row_index, col_index]
            if pd.isna(value):
                continue
            month = detect_month_from_header_text(str(value))
            if month is not None and 1 <= int(month) <= 12:
                row_month_cols[col_index] = int(month)

        if len(row_month_cols) >= 12:
            ordered_cols = sorted(row_month_cols)
            # 注释区表头可能把 2024.10 读成 2024.1，直接按列顺序映射 1..12 更稳。
            month_cols = {
                col_index: month
                for month, col_index in enumerate(ordered_cols[:12], start=1)
            }
            header_row = row_index
            break

    if not month_cols or header_row is None:
        return {}

    balance_row = None
    search_end = min(len(sdf), header_row + 8)
    for row_index in range(header_row + 1, search_end):
        row_text = normalize_text("|".join(sdf.iloc[row_index].tolist()))
        if "余额" not in row_text and "Balance" not in row_text:
            continue

        numeric_count = sum(
            parse_numeric_cell(df.iat[row_index, col_index]) is not None
            for col_index in month_cols
        )
        if numeric_count >= 10:
            balance_row = row_index
            break

    if balance_row is None:
        return {}

    result = {}
    for col_index, month in month_cols.items():
        value = parse_numeric_cell(df.iat[balance_row, col_index])
        if value is not None:
            result[int(month)] = value
    return result


def extract_money_supply_from_df(df: pd.DataFrame, fallback_year: int):
    if df is None or df.empty:
        return []

    sdf = df.copy().fillna("").astype(str)
    row_hits = {}

    for row_index in range(len(sdf)):
        row_values = [normalize_text(x) for x in sdf.iloc[row_index].tolist()]
        row_text = "|".join(row_values)
        row_type = detect_money_row_type(row_text)
        if row_type and row_type not in row_hits:
            row_hits[row_type] = {"row_index": row_index, "row_text": row_text}

    if "m1_balance_yiyuan" not in row_hits or "m2_balance_yiyuan" not in row_hits:
        return []

    month_cols = find_month_columns(df, row_hits["m2_balance_yiyuan"]["row_index"])
    if not month_cols:
        month_cols = find_month_columns(df, row_hits["m1_balance_yiyuan"]["row_index"])

    # 只有 2025 表通常会返回 {1: 1120120, ...}；其他年份为空。
    revised_m1_base_2024 = extract_revised_m1_base_from_df(df)

    records_by_month = {}
    for value_field, hit in row_hits.items():
        row_index = hit["row_index"]
        for col_index, month in month_cols.items():
            numeric_value = parse_numeric_cell(df.iat[row_index, col_index])
            if numeric_value is None:
                continue

            item = records_by_month.setdefault(month, {
                "year": fallback_year,
                "month": int(month),
                "row_index_m1": None,
                "row_index_m2": None,
                "matched_row_m1": None,
                "matched_row_m2": None,
                "m1_yoy_base_year": None,
                "m1_yoy_base_balance_yiyuan": None,
                "m1_yoy_base_note": None,
            })
            item[value_field] = numeric_value

            if value_field == "m1_balance_yiyuan":
                item["row_index_m1"] = row_index
                item["matched_row_m1"] = str(df.iloc[row_index].tolist())
            else:
                item["row_index_m2"] = row_index
                item["matched_row_m2"] = str(df.iloc[row_index].tolist())

    records = []
    for month, item in sorted(records_by_month.items()):
        if "m1_balance_yiyuan" in item and "m2_balance_yiyuan" in item:
            if fallback_year == 2025 and int(month) in revised_m1_base_2024:
                item["m1_yoy_base_year"] = 2024
                item["m1_yoy_base_balance_yiyuan"] = revised_m1_base_2024[int(month)]
                item["m1_yoy_base_note"] = "PBC revised M1 comparable 2024 base from 2025 Money Supply note"
            records.append(item)
    return records


def extract_money_supply(filepath: str, fallback_year: int):
    sheets = try_read_excel(filepath)
    for sheet_name, df in sheets.items():
        results = extract_money_supply_from_df(df, fallback_year=fallback_year)
        if results:
            for item in results:
                item["sheet_name"] = sheet_name
            return results
    return []


def build_download_path(year: int, xls_url: str):
    basename = os.path.basename(xls_url.split("?")[0])
    return os.path.join(DOWNLOAD_DIR, f"{year}_{basename}")


def get_or_download_xls(year: int, xls_url: str):
    filepath = build_download_path(year, xls_url)
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        download_file(xls_url, filepath)
        time.sleep(DOWNLOAD_SLEEP_SECONDS)
    return filepath


def fetch_household_deposit_records():
    year_links = find_year_category_links(DEPOSIT_CATEGORY_NAME, START_YEAR, END_YEAR)
    print("找到住户存款年份页：")
    print(json.dumps(year_links, ensure_ascii=False, indent=2))

    records = []
    for year, category_url in year_links.items():
        try:
            print(f"\n处理住户存款 {year} -> {category_url}")
            xls_url = find_named_xls_url(category_url, DEPOSIT_TABLE_NAME)
            print(f"  xls: {xls_url}")
            filepath = get_or_download_xls(year, xls_url)

            monthly_results = extract_household_deposit(filepath, fallback_year=year)
            if not monthly_results:
                print(f"  未找到住户存款月度数据: {filepath}")
                records.append({
                    "year": year,
                    "month": None,
                    "date": None,
                    "household_deposits": None,
                    "source_url": xls_url,
                    "source_file": filepath,
                    "status": "NOT_FOUND",
                })
                continue

            for item in monthly_results:
                records.append({
                    "year": item["year"],
                    "month": item["month"],
                    "date": f"{item['year']}-{item['month']:02d}-01",
                    "household_deposits": item["household_deposits"],
                    "sheet_name": item.get("sheet_name"),
                    "row_index": item.get("row_index"),
                    "col_index": item.get("col_index"),
                    "matched_row": item.get("matched_row"),
                    "source_url": xls_url,
                    "source_file": filepath,
                    "status": "OK",
                })
            print(f"  提取到 {len(monthly_results)} 个月份数据")
        except Exception as exc:
            print(f"  失败: {year}, error={exc}")
            traceback.print_exc()
            records.append({
                "year": year,
                "month": None,
                "date": None,
                "household_deposits": None,
                "source_url": category_url,
                "source_file": None,
                "status": f"ERROR: {exc}",
            })
    return records


def compute_money_supply_growth(records: list[dict]):
    if not records:
        return []

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    previous_year_lookup = {
        (int(row.year), int(row.month)): row
        for row in df.itertuples(index=False)
    }

    m1_yoy_list = []
    m2_yoy_list = []
    gap_list = []
    m1_base_used_list = []
    m2_base_used_list = []
    calc_note_list = []

    for row in df.itertuples(index=False):
        previous = previous_year_lookup.get((int(row.year) - 1, int(row.month)))
        m1_yoy_pct = None
        m2_yoy_pct = None
        gap_pct = None
        m1_base_used = None
        m2_base_used = None
        calc_note = "normal YoY: current balance / previous-year same-month balance - 1"

        if previous is not None:
            previous_m1 = getattr(previous, "m1_balance_yiyuan", None)
            previous_m2 = getattr(previous, "m2_balance_yiyuan", None)

            # 关键修正：2025 年 M1 同比，优先用央行表注释里的 2024 可比口径 M1 余额。
            comparable_base = getattr(row, "m1_yoy_base_balance_yiyuan", None)
            if comparable_base is not None and pd.notna(comparable_base):
                previous_m1 = comparable_base
                calc_note = "2025 M1 YoY uses PBC revised comparable 2024 M1 base from note"

            if previous_m1 not in (None, 0) and pd.notna(previous_m1):
                m1_yoy_pct = (row.m1_balance_yiyuan / previous_m1 - 1) * 100
                m1_base_used = previous_m1
            if previous_m2 not in (None, 0) and pd.notna(previous_m2):
                m2_yoy_pct = (row.m2_balance_yiyuan / previous_m2 - 1) * 100
                m2_base_used = previous_m2
            if m1_yoy_pct is not None and m2_yoy_pct is not None:
                gap_pct = m1_yoy_pct - m2_yoy_pct

        m1_yoy_list.append(m1_yoy_pct)
        m2_yoy_list.append(m2_yoy_pct)
        gap_list.append(gap_pct)
        m1_base_used_list.append(m1_base_used)
        m2_base_used_list.append(m2_base_used)
        calc_note_list.append(calc_note)

    df["m1_yoy_pct"] = m1_yoy_list
    df["m2_yoy_pct"] = m2_yoy_list
    df["m1_m2_growth_gap_pct"] = gap_list
    df["m1_base_used_yiyuan"] = m1_base_used_list
    df["m2_base_used_yiyuan"] = m2_base_used_list
    df["calculation_note"] = calc_note_list

    df = df[df["year"] >= START_YEAR].copy()
    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    ordered_columns = [
        "year", "month", "date",
        "m1_balance_yiyuan", "m2_balance_yiyuan",
        "m1_yoy_pct", "m2_yoy_pct", "m1_m2_growth_gap_pct",
        "m1_base_used_yiyuan", "m2_base_used_yiyuan", "calculation_note",
        "m1_yoy_base_year", "m1_yoy_base_balance_yiyuan", "m1_yoy_base_note",
        "sheet_name", "row_index_m1", "row_index_m2",
        "matched_row_m1", "matched_row_m2",
        "source_url", "source_file", "status",
    ]
    for col in ordered_columns:
        if col not in df.columns:
            df[col] = None
    return df[ordered_columns].to_dict(orient="records")


def fetch_money_supply_records():
    # 为了算 START_YEAR 的同比，必须多取前一年作为基数。
    base_year = min(MONEY_BASE_YEAR, max(1999, START_YEAR - 1))
    year_links = find_year_category_links(MONEY_CATEGORY_NAME, base_year, END_YEAR)
    print("\n找到货币供应量年份页：")
    print(json.dumps(year_links, ensure_ascii=False, indent=2))

    records = []
    for year, category_url in year_links.items():
        try:
            print(f"\n处理货币供应量 {year} -> {category_url}")
            xls_url = find_named_xls_url(category_url, MONEY_TABLE_NAME)
            print(f"  xls: {xls_url}")
            filepath = get_or_download_xls(year, xls_url)

            monthly_results = extract_money_supply(filepath, fallback_year=year)
            if not monthly_results:
                # 如果本地缓存曾误存了汇率表等错误文件，删掉后强制重新下载一次。
                print(f"  未找到货币供应量月度数据，尝试删除缓存后重新下载: {filepath}")
                if os.path.exists(filepath):
                    os.remove(filepath)
                filepath = get_or_download_xls(year, xls_url)
                monthly_results = extract_money_supply(filepath, fallback_year=year)

            if not monthly_results:
                records.append({
                    "year": year,
                    "month": None,
                    "date": None,
                    "m1_balance_yiyuan": None,
                    "m2_balance_yiyuan": None,
                    "source_url": xls_url,
                    "source_file": filepath,
                    "status": "NOT_FOUND",
                })
                continue

            for item in monthly_results:
                records.append({
                    "year": item["year"],
                    "month": item["month"],
                    "date": f"{item['year']}-{item['month']:02d}-01",
                    "m1_balance_yiyuan": item["m1_balance_yiyuan"],
                    "m2_balance_yiyuan": item["m2_balance_yiyuan"],
                    "m1_yoy_base_year": item.get("m1_yoy_base_year"),
                    "m1_yoy_base_balance_yiyuan": item.get("m1_yoy_base_balance_yiyuan"),
                    "m1_yoy_base_note": item.get("m1_yoy_base_note"),
                    "sheet_name": item.get("sheet_name"),
                    "row_index_m1": item.get("row_index_m1"),
                    "row_index_m2": item.get("row_index_m2"),
                    "matched_row_m1": item.get("matched_row_m1"),
                    "matched_row_m2": item.get("matched_row_m2"),
                    "source_url": xls_url,
                    "source_file": filepath,
                    "status": "OK",
                })
            print(f"  提取到 {len(monthly_results)} 个月份数据")
        except Exception as exc:
            print(f"  失败: {year}, error={exc}")
            traceback.print_exc()
            records.append({
                "year": year,
                "month": None,
                "date": None,
                "m1_balance_yiyuan": None,
                "m2_balance_yiyuan": None,
                "source_url": category_url,
                "source_file": None,
                "status": f"ERROR: {exc}",
            })
    return compute_money_supply_growth(records)


def extract_social_financing_from_df(df: pd.DataFrame, fallback_year: int):
    if df is None or df.empty:
        return []

    candidate_rows = []
    for row_index in range(len(df)):
        year_month = parse_year_month_label(df.iat[row_index, 0])
        if not year_month:
            continue

        year, _ = year_month
        if year != fallback_year:
            continue

        afre_flow = parse_numeric_cell(df.iat[row_index, 1])
        if afre_flow is None:
            continue

        candidate_rows.append({
            "year": year,
            "afre_flow_yiyuan": afre_flow,
            "sheet_name": "Sheet1",
            "row_index": row_index,
            "source_row": str(df.iloc[row_index].tolist()),
        })

    records = []
    for month, item in enumerate(candidate_rows, start=1):
        records.append({
            "year": item["year"],
            "month": month,
            "afre_flow_yiyuan": item["afre_flow_yiyuan"],
            "sheet_name": item["sheet_name"],
            "row_index": item["row_index"],
            "source_row": item["source_row"],
        })

    return sorted(records, key=lambda item: item["month"])


def extract_social_financing(filepath: str, fallback_year: int):
    sheets = try_read_excel(filepath)
    for sheet_name, df in sheets.items():
        results = extract_social_financing_from_df(df, fallback_year=fallback_year)
        if results:
            for item in results:
                item["sheet_name"] = sheet_name
            return results
    return []


def fetch_social_financing_records():
    base_year = max(START_YEAR, END_YEAR - 2)
    year_links = find_year_category_links(SOCIAL_FINANCING_CATEGORY_NAME, base_year, END_YEAR)
    print("\n找到社会融资规模年份页：")
    print(json.dumps(year_links, ensure_ascii=False, indent=2))

    records = []
    for year, category_url in year_links.items():
        try:
            print(f"\n处理社会融资规模 {year} -> {category_url}")
            xls_url = find_named_xls_url(category_url, SOCIAL_FINANCING_TABLE_NAME)
            print(f"  xls: {xls_url}")
            filepath = get_or_download_xls(year, xls_url)

            monthly_results = extract_social_financing(filepath, fallback_year=year)
            if not monthly_results:
                print(f"  未找到社融月度数据: {filepath}")
                records.append({
                    "year": year,
                    "month": None,
                    "date": None,
                    "afre_flow_yiyuan": None,
                    "source_url": xls_url,
                    "source_file": filepath,
                    "status": "NOT_FOUND",
                })
                continue

            for item in monthly_results:
                records.append({
                    "year": item["year"],
                    "month": item["month"],
                    "date": f"{item['year']}-{item['month']:02d}-01",
                    "afre_flow_yiyuan": item["afre_flow_yiyuan"],
                    "afre_flow_wanyiyuan": item["afre_flow_yiyuan"] / 10000,
                    "sheet_name": item.get("sheet_name"),
                    "row_index": item.get("row_index"),
                    "source_row": item.get("source_row"),
                    "source_url": xls_url,
                    "source_file": filepath,
                    "status": "OK",
                })
            print(f"  提取到 {len(monthly_results)} 个月份数据")
        except Exception as exc:
            print(f"  失败: {year}, error={exc}")
            traceback.print_exc()
            records.append({
                "year": year,
                "month": None,
                "date": None,
                "afre_flow_yiyuan": None,
                "source_url": category_url,
                "source_file": None,
                "status": f"ERROR: {exc}",
            })

    if not records:
        return []

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values(["year", "month"], na_position="last").reset_index(drop=True)
    return df.to_dict(orient="records")


def fetch_latest_pmi_release_url():
    candidates = []
    errors = []
    scanned_urls = list(dict.fromkeys(iter_pmi_release_list_urls()))

    for list_url in scanned_urls:
        try:
            soup = get_soup(list_url)
        except Exception as exc:
            errors.append(f"{list_url}: {exc}")
            continue

        for anchor in soup.find_all("a", href=True):
            text = anchor.get("title") or anchor.get_text(" ", strip=True)
            text = " ".join(str(text).split())
            if "中国采购经理指数运行情况" not in text:
                continue

            href = urljoin(list_url, anchor["href"])
            month_info = parse_year_month_label(text)
            if month_info:
                candidates.append((month_info[0], month_info[1], href, text))

    if not candidates:
        message = "未在统计局发布列表中找到 PMI 月报链接"
        if scanned_urls:
            message += "，已扫描: " + ", ".join(scanned_urls)
        if errors:
            message += "；部分页面读取失败: " + " | ".join(errors)
        raise RuntimeError(message)

    candidates.sort()
    _, _, href, _ = candidates[-1]
    return href


def extract_pmi_records_from_url(url: str):
    html = fetch_html(url)
    tables = pd.read_html(StringIO(html))
    target_table = None
    for table in tables:
        flattened = "".join(str(value) for value in table.head(5).fillna("").to_numpy().flatten().tolist())
        if "PMI" in flattened:
            target_table = table
            break

    if target_table is None:
        raise RuntimeError(f"未在 PMI 页面找到制造业 PMI 表: {url}")

    records = []
    for _, row in target_table.iterrows():
        year_month = parse_year_month_label(row.iloc[0])
        if not year_month:
            continue

        pmi_value = parse_numeric_cell(row.iloc[1])
        if pmi_value is None:
            continue

        year, month = year_month
        records.append({
            "year": year,
            "month": month,
            "date": f"{year}-{month:02d}-01",
            "manufacturing_pmi": pmi_value,
            "source_url": url,
            "status": "OK",
        })

    return records


def fetch_pmi_records():
    urls = []
    try:
        urls.append(fetch_latest_pmi_release_url())
    except Exception as exc:
        print(f"\nPMI 最新发布链接查找失败，将继续使用备用链接和历史数据: {exc}")

    if PMI_BOOTSTRAP_URL:
        urls.append(PMI_BOOTSTRAP_URL)
    urls = list(dict.fromkeys(urls))

    records = []
    for url in urls:
        try:
            print(f"\n处理 PMI -> {url}")
            monthly_results = extract_pmi_records_from_url(url)
            print(f"  提取到 {len(monthly_results)} 个月份数据")
            records.extend(monthly_results)
        except Exception as exc:
            print(f"  失败: url={url}, error={exc}")
            traceback.print_exc()

    if os.path.exists(PMI_OUTPUT_CSV):
        try:
            history_df = pd.read_csv(PMI_OUTPUT_CSV)
            if not history_df.empty:
                history_df["status"] = history_df.get("status", "HISTORY")
                records.extend(history_df.to_dict(orient="records"))
        except Exception:
            traceback.print_exc()

    if not records:
        return []

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["manufacturing_pmi"] = pd.to_numeric(df["manufacturing_pmi"], errors="coerce")
    df = df.dropna(subset=["date", "manufacturing_pmi"]).copy()
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    if len(df) > PMI_LOOKBACK_MONTHS:
        df = df.tail(PMI_LOOKBACK_MONTHS).reset_index(drop=True)

    ordered_columns = ["year", "month", "date", "manufacturing_pmi", "source_url", "status"]
    for col in ordered_columns:
        if col not in df.columns:
            df[col] = None
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df[ordered_columns].to_dict(orient="records")


def main():
    ensure_dir(DOWNLOAD_DIR)

    deposit_records = fetch_household_deposit_records()
    deposit_df = pd.DataFrame(deposit_records)
    if not deposit_df.empty:
        deposit_df = deposit_df.sort_values(["year", "month"], na_position="last").reset_index(drop=True)
    deposit_df.to_csv(DEPOSIT_OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n完成，输出住户存款: {DEPOSIT_OUTPUT_CSV}")

    money_supply_records = fetch_money_supply_records()
    money_supply_df = pd.DataFrame(money_supply_records)
    if not money_supply_df.empty:
        money_supply_df = money_supply_df.sort_values(["year", "month"], na_position="last").reset_index(drop=True)
    money_supply_df.to_csv(MONEY_OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"完成，输出货币供应量: {MONEY_OUTPUT_CSV}")

    social_financing_records = fetch_social_financing_records()
    social_financing_df = pd.DataFrame(social_financing_records)
    if not social_financing_df.empty:
        social_financing_df = social_financing_df.sort_values(["year", "month"], na_position="last").reset_index(drop=True)
    social_financing_df.to_csv(SOCIAL_FINANCING_OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"完成，输出社会融资规模: {SOCIAL_FINANCING_OUTPUT_CSV}")

    pmi_records = fetch_pmi_records()
    pmi_df = pd.DataFrame(pmi_records)
    if not pmi_df.empty:
        pmi_df = pmi_df.sort_values(["year", "month"], na_position="last").reset_index(drop=True)
    pmi_df.to_csv(PMI_OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"完成，输出制造业 PMI: {PMI_OUTPUT_CSV}")


if __name__ == "__main__":
    main()
