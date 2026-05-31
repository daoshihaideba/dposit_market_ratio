import json
import os
from pathlib import Path
from urllib.parse import quote

import requests


SENDKEY_ENV_VAR = "FTQQ_SENDKEY"
SUMMARY_JSON = os.getenv("RATIO_SUMMARY_JSON", "deposit_market_ratio_summary.json")
IMAGE_PATH = os.getenv("RATIO_OUTPUT_IMAGE", "deposit_market_ratio_trend.png")
CSV_PATH = os.getenv("RATIO_OUTPUT_CSV", "deposit_market_ratio.csv")
PAGES_BASE_URL = os.getenv("PAGES_BASE_URL", "").strip()


def append_cache_buster(url: str, token: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}v={token}"


def build_public_file_url(path: str) -> str | None:
    normalized = quote(Path(path).as_posix())

    if PAGES_BASE_URL:
        return f"{PAGES_BASE_URL.rstrip('/')}/{normalized}"

    repository = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("GITHUB_REF_NAME")
    if not repository or not branch:
        return None

    return f"https://raw.githubusercontent.com/{repository}/{branch}/{normalized}"


def load_summary(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def build_message(summary: dict) -> tuple[str, str]:
    cache_token = summary["generated_at_utc"].replace(":", "").replace("-", "")
    image_url = build_public_file_url(IMAGE_PATH)
    csv_url = build_public_file_url(CSV_PATH)
    page_url = f"{PAGES_BASE_URL.rstrip('/')}/index.html" if PAGES_BASE_URL else None

    if image_url:
        image_url = append_cache_buster(image_url, cache_token)

    title = f"存市比/剪刀差日报 {summary['latest_month']} | {summary['deposit_market_ratio']:.3f}"
    lines = [
        "# 中国住户存款 / A股总市值 存市比日报",
        "",
        f"- 月份: {summary['latest_month']}",
        f"- 住户存款: {summary['household_deposits_wanyiyuan']:.2f} 万亿元",
        f"- A股总市值: {summary['a_share_market_value_wanyiyuan']:.2f} 万亿元",
        f"- 存市比: {summary['deposit_market_ratio']:.3f}",
        f"- 较上月变化: {summary['ratio_mom_change']:+.3f}" if summary["ratio_mom_change"] is not None else "- 较上月变化: N/A",
        f"- 环比: {summary['ratio_mom_pct_change']:+.2%}" if summary["ratio_mom_pct_change"] is not None else "- 环比: N/A",
        f"- 股票市值取值日: {summary['latest_trade_date']}",
        f"- M1同比: {summary['m1_yoy_pct']:+.2f}%",
        f"- M2同比: {summary['m2_yoy_pct']:+.2f}%",
        f"- M1-M2剪刀差: {summary['m1_m2_growth_gap_pct']:+.2f} 个百分点",
        f"- 制造业PMI: {summary['manufacturing_pmi']:.1f}",
        f"- 社融增量: {summary['afre_flow_wanyiyuan']:.2f} 万亿元",
    ]

    if image_url:
        lines.extend(["", f"![存市比趋势图]({image_url})"])

    link_lines = []
    if page_url:
        link_lines.append(f"[打开网页版]({page_url})")
    if image_url:
        link_lines.append(f"[打开趋势图]({image_url})")
    if csv_url:
        link_lines.append(f"[打开明细CSV]({csv_url})")
    if link_lines:
        lines.extend(["", " | ".join(link_lines)])

    return title, "\n".join(lines)


def main():
    sendkey = os.getenv(SENDKEY_ENV_VAR, "").strip()
    if not sendkey:
        print(f"未设置 {SENDKEY_ENV_VAR}，跳过方糖推送。")
        return

    summary = load_summary(SUMMARY_JSON)
    title, desp = build_message(summary)

    response = requests.post(
        f"https://sctapi.ftqq.com/{sendkey}.send",
        data={"title": title, "desp": desp},
        timeout=30,
    )
    response.raise_for_status()

    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"方糖推送失败: {payload}")

    print("方糖推送成功。")


if __name__ == "__main__":
    main()
