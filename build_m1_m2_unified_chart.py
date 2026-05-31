import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


MONEY_SUPPLY_CSV = os.getenv("MONEY_SUPPLY_OUTPUT_CSV", "pboc_money_supply.csv")
DISPLAY_START = os.getenv("M1_M2_UNIFIED_START", "2024-05-01")
M1_REVISION_MONTH = os.getenv("M1_REVISION_MONTH", "2025-01")
OUTPUT_CSV = os.getenv("M1_M2_UNIFIED_OUTPUT_CSV", "m1_m2_unified_gap_since_2025.csv")
OUTPUT_IMAGE = os.getenv("M1_M2_UNIFIED_OUTPUT_IMAGE", "m1_m2_unified_gap_since_2025.png")
OUTPUT_SUMMARY_JSON = os.getenv("M1_M2_UNIFIED_SUMMARY_JSON", "m1_m2_unified_gap_summary.json")

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


def draw_dashed_vertical_line(draw, x, top, bottom, fill, width=2, dash=12, gap=8):
    current_y = top
    while current_y < bottom:
        end_y = min(current_y + dash, bottom)
        draw.line((x, current_y, x, end_y), fill=fill, width=width)
        current_y = end_y + gap


def draw_rotated_text(image, xy, text, font, fill, angle):
    dummy = Image.new("RGBA", (1, 1), (255, 255, 255, 0))
    dummy_draw = ImageDraw.Draw(dummy)
    bbox = dummy_draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    text_image = Image.new("RGBA", (text_width + 8, text_height + 8), (255, 255, 255, 0))
    text_draw = ImageDraw.Draw(text_image)
    text_draw.text((4, 4), text, font=font, fill=fill)

    rotated = text_image.rotate(angle, expand=True)
    image.alpha_composite(rotated, (int(xy[0]), int(xy[1])))


def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "status" in df.columns:
        df = df[df["status"] == "OK"].copy()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for column in [
        "m1_balance_yiyuan",
        "m2_balance_yiyuan",
        "m1_yoy_pct",
        "m2_yoy_pct",
        "m1_m2_growth_gap_pct",
        "m1_yoy_base_balance_yiyuan",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=["date", "m1_yoy_pct", "m2_yoy_pct", "m1_m2_growth_gap_pct"]).copy()
    df = df[df["date"] >= pd.Timestamp(DISPLAY_START)].copy()
    df = df.sort_values("date").reset_index(drop=True)
    if df.empty:
        raise RuntimeError("M1-M2 剪刀差样本为空，请检查 pboc_money_supply.csv 是否已生成。")

    df["month"] = df["date"].dt.strftime("%Y-%m")
    return df


def build_summary(df: pd.DataFrame) -> dict:
    latest = df.iloc[-1]
    lowest = df.loc[df["m1_m2_growth_gap_pct"].idxmin()]
    highest = df.loc[df["m1_m2_growth_gap_pct"].idxmax()]
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "start_month": df.iloc[0]["month"],
        "latest_month": latest["month"],
        "latest_date": str(latest["date"])[:10],
        "m1_yoy_pct": float(latest["m1_yoy_pct"]),
        "m2_yoy_pct": float(latest["m2_yoy_pct"]),
        "m1_m2_growth_gap_pct": float(latest["m1_m2_growth_gap_pct"]),
        "lowest_month": lowest["month"],
        "lowest_gap_pct": float(lowest["m1_m2_growth_gap_pct"]),
        "highest_month": highest["month"],
        "highest_gap_pct": float(highest["m1_m2_growth_gap_pct"]),
        "points": int(len(df)),
        "image_file": OUTPUT_IMAGE,
    }


def render_png(df: pd.DataFrame, summary: dict, output_path: str):
    width = 1600
    height = 1060
    chart_left = 90
    chart_top = 170
    chart_width = 1440
    chart_height = 600

    image = Image.new("RGBA", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)

    font_title = load_font(40, bold=True)
    font_subtitle = load_font(24)
    font_axis = load_font(16)
    font_note = load_font(20)

    draw_text(draw, (width // 2, 54), "China M1-M2 Growth Gap: M1 YoY - M2 YoY", font_title, "#0f172a", anchor="ma")
    draw_text(draw, (width // 2, 98), f"{summary['start_month']} to {summary['latest_month']}", font_subtitle, "#334155", anchor="ma")

    draw.rectangle((chart_left, chart_top, chart_left + chart_width, chart_top + chart_height), outline="#cbd5e1", width=2)

    points, y_min, y_max = scale_points(df["m1_m2_growth_gap_pct"].tolist(), chart_left, chart_top, chart_width, chart_height)
    tick_count = 7
    for idx in range(tick_count + 1):
        value = y_min + (y_max - y_min) * idx / tick_count
        y = chart_top + chart_height - ((value - y_min) / (y_max - y_min) * chart_height)
        draw.line((chart_left, y, chart_left + chart_width, y), fill="#e2e8f0", width=1)
        draw_text(draw, (chart_left - 18, y), f"{value:.0f}", font_axis, "#334155", anchor="ra")

    if y_min < 0 < y_max:
        zero_y = chart_top + chart_height - ((0 - y_min) / (y_max - y_min) * chart_height)
        draw.line((chart_left, zero_y, chart_left + chart_width, zero_y), fill="#60a5fa", width=2)

    for idx, row in df.iterrows():
        x, _ = points[idx]
        if row["month"].endswith("-01"):
            draw.line((x, chart_top, x, chart_top + chart_height), fill="#e2e8f0", width=1)
        month_label = row["month"][2:]
        draw_rotated_text(image, (x - 20, chart_top + chart_height + 18), month_label, font_axis, "#334155", 45)

    revision_matches = df.index[df["month"] == M1_REVISION_MONTH].tolist()
    if revision_matches:
        revision_x, _ = points[revision_matches[0]]
        draw_dashed_vertical_line(draw, revision_x, chart_top, chart_top + chart_height, "#3b82f6")
        draw_text(draw, (revision_x + 12, chart_top + chart_height - 6), "M1口径修订\n2025-01", font_note, "#334155", anchor="ls")

    draw.line(points, fill="#2b7bbb", width=5, joint="curve")
    for x, y in points:
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill="#2b7bbb")

    latest_x, latest_y = points[-1]
    draw.ellipse((latest_x - 10, latest_y - 10, latest_x + 10, latest_y + 10), fill="#2b7bbb")
    draw_text(draw, (latest_x - 10, latest_y - 18), f"{summary['latest_month']}\n{summary['m1_m2_growth_gap_pct']:+.1f}pct", font_note, "#0f172a", anchor="rs")

    lowest_index = df.index.get_loc(df["m1_m2_growth_gap_pct"].idxmin())
    low_x, low_y = points[lowest_index]
    draw_text(draw, (low_x - 10, low_y - 18), f"{summary['lowest_month']}\n{summary['lowest_gap_pct']:+.1f}pct", font_note, "#0f172a", anchor="rs")

    highest_index = df.index.get_loc(df["m1_m2_growth_gap_pct"].idxmax())
    high_x, high_y = points[highest_index]
    draw_text(draw, (high_x, high_y - 26), f"{summary['highest_month']}\n{summary['highest_gap_pct']:+.1f}pct", font_note, "#0f172a", anchor="ma")

    image.convert("RGB").save(output_path, format="PNG", optimize=True)


def main():
    df = load_data(MONEY_SUPPLY_CSV)
    out_df = df[
        [
            "month",
            "date",
            "m1_balance_yiyuan",
            "m2_balance_yiyuan",
            "m1_yoy_pct",
            "m2_yoy_pct",
            "m1_m2_growth_gap_pct",
            "m1_yoy_base_balance_yiyuan",
            "m1_yoy_base_note",
            "calculation_note",
        ]
    ].copy()
    out_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    summary = build_summary(df)
    with open(OUTPUT_SUMMARY_JSON, "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    render_png(df, summary, OUTPUT_IMAGE)

    print("完成，生成以下文件：")
    print(f"- {OUTPUT_CSV}")
    print(f"- {OUTPUT_IMAGE}")
    print(f"- {OUTPUT_SUMMARY_JSON}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
