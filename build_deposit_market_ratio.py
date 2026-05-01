import json
import math
import os
from datetime import datetime, timezone
from html import escape

import pandas as pd


DEPOSIT_CSV = os.getenv("PBOC_OUTPUT_CSV", "pboc_household_deposits.csv")
MARKET_CSV = os.getenv("A_SHARE_OUTPUT_CSV", "a_share_month_end_total_mv.csv")
OUTPUT_CSV = os.getenv("RATIO_OUTPUT_CSV", "deposit_market_ratio.csv")
OUTPUT_SVG = os.getenv("RATIO_OUTPUT_SVG", "deposit_market_ratio_trend.svg")
OUTPUT_SUMMARY_JSON = os.getenv("RATIO_SUMMARY_JSON", "deposit_market_ratio_summary.json")


def load_deposit_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "status" in df.columns:
        df = df[df["status"] == "OK"].copy()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["household_deposits"] = pd.to_numeric(df["household_deposits"], errors="coerce")
    df = df.dropna(subset=["date", "household_deposits"]).copy()
    df["year_month"] = df["date"].dt.to_period("M")
    df = df.sort_values(["year_month", "date"]).drop_duplicates("year_month", keep="last")

    return df[["year_month", "date", "household_deposits"]].reset_index(drop=True)


def load_market_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df["total_mv_sum_yiyuan"] = pd.to_numeric(df["total_mv_sum_yiyuan"], errors="coerce")
    df["stock_count"] = pd.to_numeric(df["stock_count"], errors="coerce")
    df = df.dropna(subset=["trade_date", "total_mv_sum_yiyuan"]).copy()
    df["year_month"] = df["trade_date"].dt.to_period("M")
    df = df.sort_values(["year_month", "trade_date"]).drop_duplicates("year_month", keep="last")

    return df[["year_month", "trade_date", "stock_count", "total_mv_sum_yiyuan"]].reset_index(drop=True)


def build_ratio_dataframe(deposit_df: pd.DataFrame, market_df: pd.DataFrame) -> pd.DataFrame:
    merged = deposit_df.merge(market_df, on="year_month", how="inner")
    merged = merged.sort_values("year_month").reset_index(drop=True)

    merged["month"] = merged["year_month"].astype(str)
    merged["household_deposits_yiyuan"] = merged["household_deposits"]
    merged["a_share_market_value_yiyuan"] = merged["total_mv_sum_yiyuan"]
    merged["household_deposits_wanyiyuan"] = merged["household_deposits_yiyuan"] / 10000
    merged["a_share_market_value_wanyiyuan"] = merged["a_share_market_value_yiyuan"] / 10000
    merged["deposit_market_ratio"] = (
        merged["household_deposits_yiyuan"] / merged["a_share_market_value_yiyuan"]
    )
    merged["ratio_mom_change"] = merged["deposit_market_ratio"].diff()
    merged["ratio_mom_pct_change"] = merged["deposit_market_ratio"].pct_change()

    return merged[
        [
            "month",
            "date",
            "trade_date",
            "stock_count",
            "household_deposits_yiyuan",
            "household_deposits_wanyiyuan",
            "a_share_market_value_yiyuan",
            "a_share_market_value_wanyiyuan",
            "deposit_market_ratio",
            "ratio_mom_change",
            "ratio_mom_pct_change",
        ]
    ].copy()


def format_wanyiyuan(value_yiyuan: float) -> str:
    return f"{value_yiyuan / 10000:.2f}万亿元"


def format_ratio_change(value: float) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{value:+.3f}"


def format_pct_change(value: float) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{value:+.2%}"


def scale_points(values, left, top, width, height):
    y_min = min(values)
    y_max = max(values)
    if math.isclose(y_min, y_max):
        y_min -= 0.05
        y_max += 0.05

    padding = max((y_max - y_min) * 0.1, 0.03)
    y_min -= padding
    y_max += padding

    points = []
    for index, value in enumerate(values):
        x = left if len(values) == 1 else left + (width * index / (len(values) - 1))
        y = top + height - ((value - y_min) / (y_max - y_min) * height)
        points.append((x, y))

    return points, y_min, y_max


def render_svg_chart(df: pd.DataFrame, output_path: str):
    width = 1600
    height = 960
    chart_left = 120
    chart_top = 260
    chart_width = 1360
    chart_height = 520

    ratios = df["deposit_market_ratio"].tolist()
    points, y_min, y_max = scale_points(ratios, chart_left, chart_top, chart_width, chart_height)
    latest = df.iloc[-1]

    def y_to_svg(value):
        return chart_top + chart_height - ((value - y_min) / (y_max - y_min) * chart_height)

    y_ticks = 6
    tick_values = [y_min + (y_max - y_min) * i / y_ticks for i in range(y_ticks + 1)]
    january_rows = df[df["month"].str.endswith("-01")]

    path_d = " ".join(
        f"{'M' if index == 0 else 'L'} {x:.2f} {y:.2f}"
        for index, (x, y) in enumerate(points)
    )
    area_d = (
        f"M {points[0][0]:.2f} {chart_top + chart_height:.2f} "
        + " ".join(f"L {x:.2f} {y:.2f}" for x, y in points)
        + f" L {points[-1][0]:.2f} {chart_top + chart_height:.2f} Z"
    )

    cards = [
        ("最新月份", latest["month"]),
        ("住户存款", format_wanyiyuan(latest["household_deposits_yiyuan"])),
        ("A股总市值", format_wanyiyuan(latest["a_share_market_value_yiyuan"])),
        ("存市比", f"{latest['deposit_market_ratio']:.3f}"),
    ]

    card_svg = []
    card_width = 310
    card_height = 95
    card_gap = 24
    start_x = 120
    start_y = 90
    for index, (label, value) in enumerate(cards):
        x = start_x + index * (card_width + card_gap)
        card_svg.append(
            f"""
            <g>
              <rect x="{x}" y="{start_y}" width="{card_width}" height="{card_height}" rx="24" fill="#ffffff" opacity="0.95" />
              <text x="{x + 28}" y="{start_y + 36}" font-size="20" fill="#64748b">{escape(label)}</text>
              <text x="{x + 28}" y="{start_y + 70}" font-size="32" font-weight="700" fill="#0f172a">{escape(value)}</text>
            </g>
            """
        )

    year_tick_svg = []
    for _, row in january_rows.iterrows():
        idx = df.index[df["month"] == row["month"]][0]
        x, _ = points[idx]
        year_tick_svg.append(
            f"""
            <line x1="{x:.2f}" y1="{chart_top}" x2="{x:.2f}" y2="{chart_top + chart_height}" stroke="#dbeafe" stroke-dasharray="4 8" />
            <text x="{x:.2f}" y="{chart_top + chart_height + 34}" text-anchor="middle" font-size="18" fill="#64748b">{escape(row["month"][:4])}</text>
            """
        )

    y_tick_svg = []
    for value in tick_values:
        y = y_to_svg(value)
        y_tick_svg.append(
            f"""
            <line x1="{chart_left}" y1="{y:.2f}" x2="{chart_left + chart_width}" y2="{y:.2f}" stroke="#cbd5e1" stroke-dasharray="4 8" />
            <text x="{chart_left - 20}" y="{y + 6:.2f}" text-anchor="end" font-size="18" fill="#64748b">{value:.2f}</text>
            """
        )

    latest_x, latest_y = points[-1]
    footnote = (
        "数据口径：住户存款来自人民银行金融机构人民币信贷收支表；"
        "A股总市值来自 Tushare daily_basic，并按每月最后一个交易日聚合。"
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0%" stop-color="#eff6ff" />
      <stop offset="100%" stop-color="#fff7ed" />
    </linearGradient>
    <linearGradient id="line" x1="0" x2="1" y1="0" y2="0">
      <stop offset="0%" stop-color="#2563eb" />
      <stop offset="100%" stop-color="#ea580c" />
    </linearGradient>
    <linearGradient id="area" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0%" stop-color="#60a5fa" stop-opacity="0.28" />
      <stop offset="100%" stop-color="#60a5fa" stop-opacity="0.02" />
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" fill="url(#bg)" />
  <text x="120" y="56" font-size="42" font-weight="800" fill="#0f172a">中国住户存款 / A股总市值 存市比趋势</text>
  <text x="120" y="92" font-size="22" fill="#475569">时间区间：{escape(df.iloc[0]['month'])} 到 {escape(latest['month'])}，每日任务自动刷新</text>
  {''.join(card_svg)}
  <rect x="{chart_left}" y="{chart_top}" width="{chart_width}" height="{chart_height}" rx="28" fill="#ffffff" opacity="0.82" />
  {''.join(year_tick_svg)}
  {''.join(y_tick_svg)}
  <path d="{area_d}" fill="url(#area)" />
  <path d="{path_d}" fill="none" stroke="url(#line)" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" />
  <circle cx="{latest_x:.2f}" cy="{latest_y:.2f}" r="8" fill="#ea580c" />
  <circle cx="{latest_x:.2f}" cy="{latest_y:.2f}" r="16" fill="#ea580c" opacity="0.18" />
  <text x="{latest_x - 12:.2f}" y="{latest_y - 18:.2f}" text-anchor="end" font-size="20" font-weight="700" fill="#9a3412">{latest['deposit_market_ratio']:.3f}</text>
  <text x="{chart_left}" y="{chart_top - 22}" font-size="20" fill="#334155">存市比（住户存款 / A股总市值）</text>
  <text x="{chart_left}" y="840" font-size="22" font-weight="700" fill="#0f172a">最新说明</text>
  <text x="{chart_left}" y="878" font-size="20" fill="#334155">住户存款月份：{escape(latest['month'])}，股票市值取值日：{escape(str(latest['trade_date'])[:10])}</text>
  <text x="{chart_left}" y="910" font-size="20" fill="#334155">较上月变化：{format_ratio_change(latest['ratio_mom_change'])}，环比：{format_pct_change(latest['ratio_mom_pct_change'])}</text>
  <text x="{chart_left}" y="940" font-size="18" fill="#64748b">{escape(footnote)}</text>
</svg>
"""

    with open(output_path, "w", encoding="utf-8") as file:
        file.write(svg)


def build_summary(df: pd.DataFrame) -> dict:
    latest = df.iloc[-1]
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_month": latest["month"],
        "latest_deposit_date": str(latest["date"])[:10],
        "latest_trade_date": str(latest["trade_date"])[:10],
        "household_deposits_yiyuan": float(latest["household_deposits_yiyuan"]),
        "household_deposits_wanyiyuan": float(latest["household_deposits_wanyiyuan"]),
        "a_share_market_value_yiyuan": float(latest["a_share_market_value_yiyuan"]),
        "a_share_market_value_wanyiyuan": float(latest["a_share_market_value_wanyiyuan"]),
        "deposit_market_ratio": float(latest["deposit_market_ratio"]),
        "ratio_mom_change": None if pd.isna(latest["ratio_mom_change"]) else float(latest["ratio_mom_change"]),
        "ratio_mom_pct_change": None if pd.isna(latest["ratio_mom_pct_change"]) else float(latest["ratio_mom_pct_change"]),
        "series_points": int(len(df)),
    }
    return summary


def main():
    deposit_df = load_deposit_data(DEPOSIT_CSV)
    market_df = load_market_data(MARKET_CSV)
    ratio_df = build_ratio_dataframe(deposit_df, market_df)

    if ratio_df.empty:
        raise RuntimeError("没有可用的存市比数据，请先确认两份源 CSV 都已成功生成。")

    ratio_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    render_svg_chart(ratio_df, OUTPUT_SVG)

    summary = build_summary(ratio_df)
    with open(OUTPUT_SUMMARY_JSON, "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    print("完成，生成以下文件：")
    print(f"- {OUTPUT_CSV}")
    print(f"- {OUTPUT_SVG}")
    print(f"- {OUTPUT_SUMMARY_JSON}")
    print("\n最新存市比摘要：")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
