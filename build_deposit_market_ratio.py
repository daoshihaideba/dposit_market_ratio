import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


DEPOSIT_CSV = os.getenv("PBOC_OUTPUT_CSV", "pboc_household_deposits.csv")
MARKET_CSV = os.getenv("A_SHARE_OUTPUT_CSV", "a_share_month_end_total_mv.csv")
MONEY_SUPPLY_CSV = os.getenv("MONEY_SUPPLY_OUTPUT_CSV", "pboc_money_supply.csv")
PMI_CSV = os.getenv("PMI_OUTPUT_CSV", "china_manufacturing_pmi.csv")
SOCIAL_FINANCING_CSV = os.getenv("SOCIAL_FINANCING_OUTPUT_CSV", "pboc_social_financing_flow.csv")
OUTPUT_CSV = os.getenv("RATIO_OUTPUT_CSV", "deposit_market_ratio.csv")
OUTPUT_IMAGE = os.getenv("RATIO_OUTPUT_IMAGE", "deposit_market_ratio_trend.png")
OUTPUT_SUMMARY_JSON = os.getenv("RATIO_SUMMARY_JSON", "deposit_market_ratio_summary.json")
M1_REVISION_MONTH = os.getenv("M1_REVISION_MONTH", "2025-01")

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


def draw_text(draw, xy, text, font, fill, anchor=None):
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def draw_dashed_vertical_line(draw, x, top, bottom, fill, width=2, dash=10, gap=8):
    current_y = top
    while current_y < bottom:
        end_y = min(current_y + dash, bottom)
        draw.line((x, current_y, x, end_y), fill=fill, width=width)
        current_y = end_y + gap


def format_trillion_rmb(value_yiyuan: float) -> str:
    return f"{value_yiyuan / 10000:.2f} tn RMB"


def scale_points(values, left, top, width, height, min_padding=0.03):
    y_min = min(values)
    y_max = max(values)
    if math.isclose(y_min, y_max):
        y_min -= 0.05
        y_max += 0.05

    padding = max((y_max - y_min) * 0.1, min_padding)
    y_min -= padding
    y_max += padding

    points = []
    for index, value in enumerate(values):
        x = left if len(values) == 1 else left + (width * index / (len(values) - 1))
        y = top + height - ((value - y_min) / (y_max - y_min) * height)
        points.append((x, y))

    return points, y_min, y_max


def build_series_points(df: pd.DataFrame, column: str, left: int, top: int, width: int, height: int):
    valid = df.dropna(subset=[column]).copy()
    if valid.empty:
        return [], None, None

    values = valid[column].tolist()
    scaled_points, y_min, y_max = scale_points(values, left, top, width, height)
    points = []
    for (_, row), (x, y) in zip(valid.iterrows(), scaled_points):
        points.append((row["month"], x, y, row[column]))
    return points, y_min, y_max


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


def load_money_supply_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "status" in df.columns:
        df = df[df["status"] == "OK"].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for column in ["m1_balance_yiyuan", "m2_balance_yiyuan", "m1_yoy_pct", "m2_yoy_pct", "m1_m2_growth_gap_pct"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["date", "m1_balance_yiyuan", "m2_balance_yiyuan"]).copy()
    df["year_month"] = df["date"].dt.to_period("M")
    df = df.sort_values(["year_month", "date"]).drop_duplicates("year_month", keep="last")
    return df[
        [
            "year_month",
            "date",
            "m1_balance_yiyuan",
            "m2_balance_yiyuan",
            "m1_yoy_pct",
            "m2_yoy_pct",
            "m1_m2_growth_gap_pct",
        ]
    ].reset_index(drop=True)


def load_pmi_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "status" in df.columns:
        df = df[df["status"] == "OK"].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["manufacturing_pmi"] = pd.to_numeric(df["manufacturing_pmi"], errors="coerce")
    df = df.dropna(subset=["date", "manufacturing_pmi"]).copy()
    df["year_month"] = df["date"].dt.to_period("M")
    df = df.sort_values(["year_month", "date"]).drop_duplicates("year_month", keep="last")
    return df[["year_month", "date", "manufacturing_pmi"]].reset_index(drop=True)


def load_social_financing_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "status" in df.columns:
        df = df[df["status"] == "OK"].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["afre_flow_yiyuan"] = pd.to_numeric(df["afre_flow_yiyuan"], errors="coerce")
    if "afre_flow_wanyiyuan" in df.columns:
        df["afre_flow_wanyiyuan"] = pd.to_numeric(df["afre_flow_wanyiyuan"], errors="coerce")
    else:
        df["afre_flow_wanyiyuan"] = df["afre_flow_yiyuan"] / 10000
    df = df.dropna(subset=["date", "afre_flow_yiyuan"]).copy()
    df["year_month"] = df["date"].dt.to_period("M")
    df = df.sort_values(["year_month", "date"]).drop_duplicates("year_month", keep="last")
    return df[["year_month", "date", "afre_flow_yiyuan", "afre_flow_wanyiyuan"]].reset_index(drop=True)


def build_ratio_dataframe(
    deposit_df: pd.DataFrame,
    market_df: pd.DataFrame,
    money_df: pd.DataFrame,
    pmi_df: pd.DataFrame,
    social_df: pd.DataFrame,
) -> pd.DataFrame:
    merged = deposit_df.merge(market_df, on="year_month", how="inner")
    merged = merged.merge(money_df.rename(columns={"date": "money_supply_date"}), on="year_month", how="left")
    merged = merged.merge(pmi_df.rename(columns={"date": "pmi_date"}), on="year_month", how="left")
    merged = merged.merge(social_df.rename(columns={"date": "social_financing_date"}), on="year_month", how="left")
    merged = merged.sort_values("year_month").reset_index(drop=True)

    merged["month"] = merged["year_month"].astype(str)
    merged["household_deposits_yiyuan"] = merged["household_deposits"]
    merged["a_share_market_value_yiyuan"] = merged["total_mv_sum_yiyuan"]
    merged["household_deposits_wanyiyuan"] = merged["household_deposits_yiyuan"] / 10000
    merged["a_share_market_value_wanyiyuan"] = merged["a_share_market_value_yiyuan"] / 10000
    merged["deposit_market_ratio"] = merged["household_deposits_yiyuan"] / merged["a_share_market_value_yiyuan"]
    merged["ratio_mom_change"] = merged["deposit_market_ratio"].diff()
    merged["ratio_mom_pct_change"] = merged["deposit_market_ratio"].pct_change()

    return merged[
        [
            "month",
            "date",
            "trade_date",
            "money_supply_date",
            "pmi_date",
            "social_financing_date",
            "stock_count",
            "household_deposits_yiyuan",
            "household_deposits_wanyiyuan",
            "a_share_market_value_yiyuan",
            "a_share_market_value_wanyiyuan",
            "deposit_market_ratio",
            "ratio_mom_change",
            "ratio_mom_pct_change",
            "m1_balance_yiyuan",
            "m2_balance_yiyuan",
            "m1_yoy_pct",
            "m2_yoy_pct",
            "m1_m2_growth_gap_pct",
            "manufacturing_pmi",
            "afre_flow_yiyuan",
            "afre_flow_wanyiyuan",
        ]
    ].copy()


def build_macro_dataframe(
    money_df: pd.DataFrame,
    pmi_df: pd.DataFrame,
    social_df: pd.DataFrame,
) -> pd.DataFrame:
    macro_df = money_df.rename(columns={"date": "money_supply_date"}).copy()
    macro_df = macro_df.merge(pmi_df.rename(columns={"date": "pmi_date"}), on="year_month", how="outer")
    macro_df = macro_df.merge(social_df.rename(columns={"date": "social_financing_date"}), on="year_month", how="outer")
    macro_df = macro_df.sort_values("year_month").reset_index(drop=True)
    macro_df["month"] = macro_df["year_month"].astype(str)
    return macro_df


def latest_non_null_row(df: pd.DataFrame, column: str) -> pd.Series:
    return df.dropna(subset=[column]).iloc[-1]


def draw_panel_axes(draw, left, top, width, height, y_min, y_max, ticks, grid_color, label_color, font):
    for tick_index in range(ticks + 1):
        value = y_min + (y_max - y_min) * tick_index / ticks
        y = top + height - ((value - y_min) / (y_max - y_min) * height)
        draw.line((left, y, left + width, y), fill=grid_color, width=1)
        draw_text(draw, (left - 18, y), f"{value:.1f}" if abs(value) < 100 else f"{value:.0f}", font, label_color, anchor="ra")


def draw_year_markers(draw, df, points, top, height, font, label_color, line_color):
    for _, row in df[df["month"].str.endswith("-01")].iterrows():
        match = [item for item in points if item[0] == row["month"]]
        if not match:
            continue
        x = match[0][1]
        draw.line((x, top, x, top + height), fill=line_color, width=1)
        draw_text(draw, (x, top + height + 28), row["month"][:4], font, label_color, anchor="ma")


def render_png_chart(df: pd.DataFrame, macro_df: pd.DataFrame, summary: dict, output_path: str):
    width = 1600
    height = 1780
    image = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 240), fill="#eef4ff")
    draw.rectangle((0, 240, width, height), fill="#fffaf5")

    font_title = load_font(40, bold=True)
    font_subtitle = load_font(22)
    font_card_label = load_font(17)
    font_card_value = load_font(24, bold=True)
    font_axis = load_font(16)
    font_note = load_font(20)
    font_small = load_font(16)

    draw_text(draw, (100, 56), "Deposit-Market Ratio + Liquidity + PMI + AFRE", font_title, "#0f172a")
    draw_text(
        draw,
        (100, 92),
        f"Monthly series from {df.iloc[0]['month']} to {df.iloc[-1]['month']} | PBOC, NBS, Tushare",
        font_subtitle,
        "#475569",
    )

    cards = [
        ("Latest Month", summary["latest_month"]),
        ("Deposits", format_trillion_rmb(summary["household_deposits_yiyuan"])),
        ("A-share MV", format_trillion_rmb(summary["a_share_market_value_yiyuan"])),
        ("Ratio", f"{summary['deposit_market_ratio']:.3f}"),
        ("M1-M2 Gap", f"{summary['m1_m2_growth_gap_pct']:+.2f} pct"),
        ("PMI", f"{summary['manufacturing_pmi']:.1f}"),
        ("AFRE Flow", f"{summary['afre_flow_wanyiyuan']:.2f} tn RMB"),
    ]

    card_width = 190
    card_height = 92
    card_gap = 16
    card_start_x = 90
    card_start_y = 128
    for index, (label, value) in enumerate(cards):
        x = card_start_x + index * (card_width + card_gap)
        draw.rounded_rectangle((x, card_start_y, x + card_width, card_start_y + card_height), radius=22, fill="#ffffff", outline="#dbeafe", width=2)
        draw_text(draw, (x + 18, card_start_y + 16), label, font_card_label, "#64748b")
        draw_text(draw, (x + 18, card_start_y + 48), value, font_card_value, "#0f172a")

    ratio_left, ratio_top, ratio_width, ratio_height = 110, 300, 1360, 280
    gap_left, gap_top, gap_width, gap_height = 110, 660, 1360, 220
    pmi_left, pmi_top, pmi_width, pmi_height = 110, 960, 1360, 220
    afre_left, afre_top, afre_width, afre_height = 110, 1260, 1360, 220

    for left, top, panel_width, panel_height, fill, outline in [
        (ratio_left, ratio_top, ratio_width, ratio_height, "#ffffff", "#dbeafe"),
        (gap_left, gap_top, gap_width, gap_height, "#ffffff", "#bfdbfe"),
        (pmi_left, pmi_top, pmi_width, pmi_height, "#ffffff", "#bbf7d0"),
        (afre_left, afre_top, afre_width, afre_height, "#ffffff", "#fde68a"),
    ]:
        draw.rounded_rectangle((left, top, left + panel_width, top + panel_height), radius=28, fill=fill, outline=outline, width=2)

    ratio_points, ratio_y_min, ratio_y_max = build_series_points(df, "deposit_market_ratio", ratio_left, ratio_top, ratio_width, ratio_height)
    macro_window_df = macro_df[macro_df["month"] >= summary["macro_display_start"]].copy()
    gap_points, gap_y_min, gap_y_max = build_series_points(macro_window_df, "m1_m2_growth_gap_pct", gap_left, gap_top, gap_width, gap_height)
    pmi_points, pmi_y_min, pmi_y_max = build_series_points(macro_window_df, "manufacturing_pmi", pmi_left, pmi_top, pmi_width, pmi_height)
    afre_points, afre_y_min, afre_y_max = build_series_points(macro_window_df, "afre_flow_wanyiyuan", afre_left, afre_top, afre_width, afre_height)

    draw_panel_axes(draw, ratio_left, ratio_top, ratio_width, ratio_height, ratio_y_min, ratio_y_max, 6, "#d7e1ee", "#64748b", font_axis)
    draw_panel_axes(draw, gap_left, gap_top, gap_width, gap_height, gap_y_min, gap_y_max, 5, "#dbeafe", "#64748b", font_axis)
    draw_panel_axes(draw, pmi_left, pmi_top, pmi_width, pmi_height, pmi_y_min, pmi_y_max, 5, "#dcfce7", "#64748b", font_axis)
    draw_panel_axes(draw, afre_left, afre_top, afre_width, afre_height, afre_y_min, afre_y_max, 5, "#fef3c7", "#64748b", font_axis)

    draw_year_markers(draw, df, ratio_points, ratio_top, ratio_height, font_axis, "#64748b", "#e8eef8")
    draw_year_markers(draw, macro_window_df, gap_points, gap_top, gap_height, font_axis, "#64748b", "#e2e8f0")
    draw_year_markers(draw, macro_window_df, pmi_points, pmi_top, pmi_height, font_axis, "#64748b", "#ecfccb")
    draw_year_markers(draw, macro_window_df, afre_points, afre_top, afre_height, font_axis, "#64748b", "#fef3c7")

    ratio_xy = [(item[1], item[2]) for item in ratio_points]
    ratio_area = [(ratio_xy[0][0], ratio_top + ratio_height), *ratio_xy, (ratio_xy[-1][0], ratio_top + ratio_height)]
    draw.polygon(ratio_area, fill="#dbeafe")
    draw.line(ratio_xy, fill="#2563eb", width=5, joint="curve")
    last_ratio_x, last_ratio_y = ratio_xy[-1]
    draw.ellipse((last_ratio_x - 14, last_ratio_y - 14, last_ratio_x + 14, last_ratio_y + 14), fill="#bfdbfe")
    draw.ellipse((last_ratio_x - 6, last_ratio_y - 6, last_ratio_x + 6, last_ratio_y + 6), fill="#2563eb")
    draw_text(draw, (last_ratio_x - 8, last_ratio_y - 16), f"{summary['deposit_market_ratio']:.3f}", font_note, "#1d4ed8", anchor="rs")

    if gap_y_min < 0 < gap_y_max:
        zero_y = gap_top + gap_height - ((0 - gap_y_min) / (gap_y_max - gap_y_min) * gap_height)
        draw.line((gap_left, zero_y, gap_left + gap_width, zero_y), fill="#60a5fa", width=2)
    revision_match = [item for item in gap_points if item[0] == M1_REVISION_MONTH]
    if revision_match:
        revision_x = revision_match[0][1]
        draw_dashed_vertical_line(draw, revision_x, gap_top, gap_top + gap_height, "#60a5fa", width=2)
        draw_text(draw, (revision_x + 10, gap_top + gap_height - 10), "M1口径修订\n2025-01", font_small, "#334155", anchor="ls")
    gap_xy = [(item[1], item[2]) for item in gap_points]
    draw.line(gap_xy, fill="#2563eb", width=5, joint="curve")
    last_gap_x, last_gap_y = gap_xy[-1]
    draw.ellipse((last_gap_x - 7, last_gap_y - 7, last_gap_x + 7, last_gap_y + 7), fill="#2563eb")
    draw_text(draw, (last_gap_x - 10, last_gap_y - 18), f"{summary['m1_m2_growth_gap_pct']:+.2f}", font_note, "#1d4ed8", anchor="rs")

    if pmi_y_min < 50 < pmi_y_max:
        threshold_y = pmi_top + pmi_height - ((50 - pmi_y_min) / (pmi_y_max - pmi_y_min) * pmi_height)
        draw.line((pmi_left, threshold_y, pmi_left + pmi_width, threshold_y), fill="#22c55e", width=2)
    pmi_xy = [(item[1], item[2]) for item in pmi_points]
    draw.line(pmi_xy, fill="#16a34a", width=5, joint="curve")
    last_pmi_x, last_pmi_y = pmi_xy[-1]
    draw.ellipse((last_pmi_x - 7, last_pmi_y - 7, last_pmi_x + 7, last_pmi_y + 7), fill="#16a34a")
    draw_text(draw, (last_pmi_x - 10, last_pmi_y - 18), f"{summary['manufacturing_pmi']:.1f}", font_note, "#15803d", anchor="rs")

    if afre_y_min < 0 < afre_y_max:
        zero_y = afre_top + afre_height - ((0 - afre_y_min) / (afre_y_max - afre_y_min) * afre_height)
        draw.line((afre_left, zero_y, afre_left + afre_width, zero_y), fill="#f59e0b", width=2)
    bar_half_width = max(6, int(afre_width / max(len(afre_points) * 4, 1)))
    for _, x, y, value in afre_points:
        baseline_y = afre_top + afre_height - ((0 - afre_y_min) / (afre_y_max - afre_y_min) * afre_height) if afre_y_min < 0 < afre_y_max else afre_top + afre_height
        top_y = min(y, baseline_y)
        bottom_y = max(y, baseline_y)
        draw.rounded_rectangle((x - bar_half_width, top_y, x + bar_half_width, bottom_y), radius=4, fill="#f59e0b")
    last_afre_x, last_afre_y = afre_points[-1][1], afre_points[-1][2]
    draw_text(draw, (last_afre_x - 10, last_afre_y - 18), f"{summary['afre_flow_wanyiyuan']:.2f}", font_note, "#b45309", anchor="rs")

    draw_text(draw, (ratio_left, ratio_top - 28), "Panel A: Household Deposits / A-share Market Value", font_note, "#334155")
    draw_text(draw, (gap_left, gap_top - 28), f"Panel B: M1 YoY - M2 YoY comparable gap since {summary['macro_display_start']}", font_note, "#334155")
    draw_text(draw, (pmi_left, pmi_top - 28), f"Panel C: Manufacturing PMI since {summary['macro_display_start']}", font_note, "#166534")
    draw_text(draw, (afre_left, afre_top - 28), f"Panel D: AFRE flow since {summary['macro_display_start']} (tn RMB)", font_note, "#92400e")

    draw_text(draw, (120, 1550), f"Latest ratio month: {summary['latest_month']} | A-share date: {summary['latest_trade_date']} | Ratio MoM: {summary['ratio_mom_change']:+.3f}", font_note, "#334155")
    draw_text(draw, (120, 1584), f"Latest monetary month: {summary['latest_money_supply_month']} | M1 YoY: {summary['m1_yoy_pct']:+.2f}% | M2 YoY: {summary['m2_yoy_pct']:+.2f}% | Gap: {summary['m1_m2_growth_gap_pct']:+.2f} pct", font_note, "#334155")
    draw_text(draw, (120, 1618), f"Latest PMI month: {summary['latest_pmi_month']} | Manufacturing PMI: {summary['manufacturing_pmi']:.1f}", font_note, "#166534")
    draw_text(draw, (120, 1652), f"Latest AFRE month: {summary['latest_social_financing_month']} | AFRE flow: {summary['afre_flow_wanyiyuan']:.2f} tn RMB", font_note, "#92400e")
    draw_text(draw, (120, 1710), "Sources: PBOC credit-receipts table, PBOC money supply table, PBOC AFRE flow table, NBS PMI release, and Tushare month-end aggregation.", font_small, "#64748b")

    image.save(output_path, format="PNG", optimize=True)


def build_summary(df: pd.DataFrame, macro_df: pd.DataFrame) -> dict:
    latest = df.iloc[-1]
    latest_gap_row = latest_non_null_row(macro_df, "m1_m2_growth_gap_pct")
    latest_pmi_row = latest_non_null_row(macro_df, "manufacturing_pmi")
    latest_afre_row = latest_non_null_row(macro_df, "afre_flow_wanyiyuan")
    latest_macro_month = max(
        pd.Period(latest_gap_row["month"], "M"),
        pd.Period(latest_pmi_row["month"], "M"),
        pd.Period(latest_afre_row["month"], "M"),
    )
    macro_display_start = str((latest_macro_month - 23))

    return {
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
        "latest_money_supply_month": latest_gap_row["month"],
        "latest_money_supply_date": str(latest_gap_row["money_supply_date"])[:10],
        "m1_balance_yiyuan": float(latest_gap_row["m1_balance_yiyuan"]),
        "m2_balance_yiyuan": float(latest_gap_row["m2_balance_yiyuan"]),
        "m1_yoy_pct": float(latest_gap_row["m1_yoy_pct"]),
        "m2_yoy_pct": float(latest_gap_row["m2_yoy_pct"]),
        "m1_m2_growth_gap_pct": float(latest_gap_row["m1_m2_growth_gap_pct"]),
        "latest_pmi_month": latest_pmi_row["month"],
        "latest_pmi_date": str(latest_pmi_row["pmi_date"])[:10],
        "manufacturing_pmi": float(latest_pmi_row["manufacturing_pmi"]),
        "latest_social_financing_month": latest_afre_row["month"],
        "latest_social_financing_date": str(latest_afre_row["social_financing_date"])[:10],
        "afre_flow_yiyuan": float(latest_afre_row["afre_flow_yiyuan"]),
        "afre_flow_wanyiyuan": float(latest_afre_row["afre_flow_wanyiyuan"]),
        "macro_display_start": macro_display_start,
        "series_points": int(len(df)),
        "image_file": OUTPUT_IMAGE,
    }


def main():
    deposit_df = load_deposit_data(DEPOSIT_CSV)
    market_df = load_market_data(MARKET_CSV)
    money_df = load_money_supply_data(MONEY_SUPPLY_CSV)
    pmi_df = load_pmi_data(PMI_CSV)
    social_df = load_social_financing_data(SOCIAL_FINANCING_CSV)

    ratio_df = build_ratio_dataframe(deposit_df, market_df, money_df, pmi_df, social_df)
    macro_df = build_macro_dataframe(money_df, pmi_df, social_df)
    if ratio_df.empty:
        raise RuntimeError("没有可用的合并数据，请先确认源 CSV 都已成功生成。")

    ratio_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    summary = build_summary(ratio_df, macro_df)
    render_png_chart(ratio_df, macro_df, summary, OUTPUT_IMAGE)

    with open(OUTPUT_SUMMARY_JSON, "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    print("完成，生成以下文件：")
    print(f"- {OUTPUT_CSV}")
    print(f"- {OUTPUT_IMAGE}")
    print(f"- {OUTPUT_SUMMARY_JSON}")
    print("\n最新摘要：")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
