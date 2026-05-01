import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


DEPOSIT_CSV = os.getenv("PBOC_OUTPUT_CSV", "pboc_household_deposits.csv")
MARKET_CSV = os.getenv("A_SHARE_OUTPUT_CSV", "a_share_month_end_total_mv.csv")
OUTPUT_CSV = os.getenv("RATIO_OUTPUT_CSV", "deposit_market_ratio.csv")
OUTPUT_IMAGE = os.getenv("RATIO_OUTPUT_IMAGE", "deposit_market_ratio_trend.png")
OUTPUT_SUMMARY_JSON = os.getenv("RATIO_SUMMARY_JSON", "deposit_market_ratio_summary.json")

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def load_font(size: int, bold: bool = False):
    candidates = list(FONT_CANDIDATES)
    if bold:
        candidates.insert(0, "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue

    return ImageFont.load_default()


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


def format_trillion_rmb(value_yiyuan: float) -> str:
    return f"{value_yiyuan / 10000:.2f} tn RMB"


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


def draw_text(draw, xy, text, font, fill, anchor=None):
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def render_png_chart(df: pd.DataFrame, output_path: str):
    width = 1600
    height = 960
    chart_left = 120
    chart_top = 270
    chart_width = 1360
    chart_height = 500

    image = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)

    # soft background bands
    draw.rectangle((0, 0, width, 220), fill="#eef4ff")
    draw.rectangle((0, 220, width, height), fill="#fffaf5")

    font_title = load_font(40, bold=True)
    font_subtitle = load_font(22)
    font_card_label = load_font(20)
    font_card_value = load_font(30, bold=True)
    font_axis = load_font(18)
    font_note = load_font(20)
    font_small = load_font(18)

    ratios = df["deposit_market_ratio"].tolist()
    points, y_min, y_max = scale_points(ratios, chart_left, chart_top, chart_width, chart_height)
    latest = df.iloc[-1]

    def y_to_png(value):
        return chart_top + chart_height - ((value - y_min) / (y_max - y_min) * chart_height)

    def round_rect(box, radius, fill, outline=None, width_value=1):
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width_value)

    draw_text(draw, (120, 56), "China Household Deposits / A-share MV Ratio", font_title, "#0f172a")
    draw_text(
        draw,
        (120, 94),
        f"Monthly series from {df.iloc[0]['month']} to {latest['month']} | refreshed daily",
        font_subtitle,
        "#475569",
    )

    cards = [
        ("Latest Month", latest["month"]),
        ("Deposits", format_trillion_rmb(latest["household_deposits_yiyuan"])),
        ("A-share MV", format_trillion_rmb(latest["a_share_market_value_yiyuan"])),
        ("Ratio", f"{latest['deposit_market_ratio']:.3f}"),
    ]

    card_width = 310
    card_height = 94
    card_gap = 24
    start_x = 120
    start_y = 120
    for index, (label, value) in enumerate(cards):
        x = start_x + index * (card_width + card_gap)
        round_rect((x, start_y, x + card_width, start_y + card_height), 24, "#ffffff", "#dbeafe", 2)
        draw_text(draw, (x + 26, start_y + 18), label, font_card_label, "#64748b")
        draw_text(draw, (x + 26, start_y + 50), value, font_card_value, "#0f172a")

    round_rect(
        (chart_left, chart_top, chart_left + chart_width, chart_top + chart_height),
        28,
        "#ffffff",
        "#dbeafe",
        2,
    )

    y_ticks = 6
    tick_values = [y_min + (y_max - y_min) * i / y_ticks for i in range(y_ticks + 1)]
    for value in tick_values:
        y = y_to_png(value)
        draw.line((chart_left, y, chart_left + chart_width, y), fill="#d7e1ee", width=1)
        draw_text(draw, (chart_left - 20, y), f"{value:.2f}", font_axis, "#64748b", anchor="ra")

    january_rows = df[df["month"].str.endswith("-01")]
    for _, row in january_rows.iterrows():
        idx = df.index[df["month"] == row["month"]][0]
        x, _ = points[idx]
        draw.line((x, chart_top, x, chart_top + chart_height), fill="#e8eef8", width=1)
        draw_text(draw, (x, chart_top + chart_height + 30), row["month"][:4], font_axis, "#64748b", anchor="ma")

    area_points = [(points[0][0], chart_top + chart_height), *points, (points[-1][0], chart_top + chart_height)]
    draw.polygon(area_points, fill="#dbeafe")
    draw.line(points, fill="#2563eb", width=5, joint="curve")

    latest_x, latest_y = points[-1]
    draw.ellipse((latest_x - 15, latest_y - 15, latest_x + 15, latest_y + 15), fill="#fed7aa", outline=None)
    draw.ellipse((latest_x - 7, latest_y - 7, latest_x + 7, latest_y + 7), fill="#ea580c", outline=None)
    draw_text(draw, (latest_x - 12, latest_y - 22), f"{latest['deposit_market_ratio']:.3f}", font_note, "#9a3412", anchor="rs")

    draw_text(draw, (chart_left, chart_top - 28), "Ratio = Household Deposits / A-share MV", font_note, "#334155")
    draw_text(
        draw,
        (chart_left, 835),
        f"Latest deposit month: {latest['month']} | Market value date: {str(latest['trade_date'])[:10]}",
        font_note,
        "#334155",
    )
    draw_text(
        draw,
        (chart_left, 872),
        f"MoM change: {format_ratio_change(latest['ratio_mom_change'])} | MoM %: {format_pct_change(latest['ratio_mom_pct_change'])}",
        font_note,
        "#334155",
    )
    draw_text(
        draw,
        (chart_left, 915),
        "Source: PBOC RMB credit-receipts table and Tushare daily_basic month-end aggregation.",
        font_small,
        "#64748b",
    )

    image.save(output_path, format="PNG", optimize=True)


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
        "image_file": OUTPUT_IMAGE,
    }
    return summary


def main():
    deposit_df = load_deposit_data(DEPOSIT_CSV)
    market_df = load_market_data(MARKET_CSV)
    ratio_df = build_ratio_dataframe(deposit_df, market_df)

    if ratio_df.empty:
        raise RuntimeError("没有可用的存市比数据，请先确认两份源 CSV 都已成功生成。")

    ratio_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    render_png_chart(ratio_df, OUTPUT_IMAGE)

    summary = build_summary(ratio_df)
    with open(OUTPUT_SUMMARY_JSON, "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    print("完成，生成以下文件：")
    print(f"- {OUTPUT_CSV}")
    print(f"- {OUTPUT_IMAGE}")
    print(f"- {OUTPUT_SUMMARY_JSON}")
    print("\n最新存市比摘要：")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
