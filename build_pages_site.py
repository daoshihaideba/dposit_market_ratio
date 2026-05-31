import json
import os
import shutil
from pathlib import Path


OUTPUT_DIR = Path(os.getenv("PAGES_OUTPUT_DIR", "pages"))
SUMMARY_JSON = Path(os.getenv("RATIO_SUMMARY_JSON", "deposit_market_ratio_summary.json"))
IMAGE_PATH = Path(os.getenv("RATIO_OUTPUT_IMAGE", "deposit_market_ratio_trend.png"))
CSV_PATH = Path(os.getenv("RATIO_OUTPUT_CSV", "deposit_market_ratio.csv"))
MONEY_SUPPLY_CSV = Path(os.getenv("MONEY_SUPPLY_OUTPUT_CSV", "pboc_money_supply.csv"))
PMI_CSV = Path(os.getenv("PMI_OUTPUT_CSV", "china_manufacturing_pmi.csv"))
SOCIAL_FINANCING_CSV = Path(os.getenv("SOCIAL_FINANCING_OUTPUT_CSV", "pboc_social_financing_flow.csv"))
UNIFIED_CSV = Path(os.getenv("M1_M2_UNIFIED_OUTPUT_CSV", "m1_m2_unified_gap_since_2025.csv"))
UNIFIED_IMAGE = Path(os.getenv("M1_M2_UNIFIED_OUTPUT_IMAGE", "m1_m2_unified_gap_since_2025.png"))
UNIFIED_SUMMARY_JSON = Path(os.getenv("M1_M2_UNIFIED_SUMMARY_JSON", "m1_m2_unified_gap_summary.json"))


def load_summary(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def write_index_html(summary: dict):
    mom_change_text = "N/A"
    if summary["ratio_mom_change"] is not None:
        mom_change_text = f"{summary['ratio_mom_change']:+.3f}"

    gap_text = f"{summary['m1_m2_growth_gap_pct']:+.2f} pct"

    html = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>存市比与M1-M2剪刀差日报</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f8fafc;
        --card: #ffffff;
        --line: #dbeafe;
        --text: #0f172a;
        --muted: #64748b;
      }}
      body {{
        margin: 0;
        font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
        background: linear-gradient(180deg, #eff6ff 0%, #fffaf5 100%);
        color: var(--text);
      }}
      main {{
        max-width: 1120px;
        margin: 0 auto;
        padding: 32px 20px 56px;
      }}
      .hero {{
        background: rgba(255,255,255,0.88);
        border: 1px solid var(--line);
        border-radius: 28px;
        padding: 24px;
        box-shadow: 0 14px 40px rgba(15, 23, 42, 0.06);
      }}
      h1 {{
        margin: 0 0 12px;
        font-size: 34px;
      }}
      .meta {{
        margin: 0;
        color: var(--muted);
        font-size: 18px;
      }}
      .grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
        gap: 16px;
        margin: 24px 0;
      }}
      .card {{
        background: var(--card);
        border: 1px solid var(--line);
        border-radius: 22px;
        padding: 18px 20px;
      }}
      .label {{
        color: var(--muted);
        font-size: 15px;
        margin-bottom: 6px;
      }}
      .value {{
        font-size: 28px;
        font-weight: 700;
      }}
      .chart {{
        margin-top: 24px;
        background: var(--card);
        border: 1px solid var(--line);
        border-radius: 28px;
        padding: 16px;
      }}
      img {{
        width: 100%;
        height: auto;
        display: block;
        border-radius: 18px;
      }}
      .links {{
        margin-top: 18px;
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
      }}
      a {{
        text-decoration: none;
        color: #1d4ed8;
        font-weight: 600;
      }}
    </style>
  </head>
  <body>
    <main>
      <section class="hero">
        <h1>中国住户存款 / A股总市值 存市比 + M1-M2剪刀差日报</h1>
        <p class="meta">最新存市比月份：{summary["latest_month"]}，最新货币数据月份：{summary["latest_money_supply_month"]}</p>
        <div class="grid">
          <div class="card">
            <div class="label">住户存款</div>
            <div class="value">{summary["household_deposits_wanyiyuan"]:.2f} 万亿元</div>
          </div>
          <div class="card">
            <div class="label">A股总市值</div>
            <div class="value">{summary["a_share_market_value_wanyiyuan"]:.2f} 万亿元</div>
          </div>
          <div class="card">
            <div class="label">存市比</div>
            <div class="value">{summary["deposit_market_ratio"]:.3f}</div>
          </div>
          <div class="card">
            <div class="label">较上月变化</div>
            <div class="value">{mom_change_text}</div>
          </div>
          <div class="card">
            <div class="label">M1-M2 剪刀差</div>
            <div class="value">{gap_text}</div>
          </div>
          <div class="card">
            <div class="label">M1 / M2 同比</div>
            <div class="value">{summary["m1_yoy_pct"]:+.2f}% / {summary["m2_yoy_pct"]:+.2f}%</div>
          </div>
          <div class="card">
            <div class="label">制造业 PMI</div>
            <div class="value">{summary["manufacturing_pmi"]:.1f}</div>
          </div>
          <div class="card">
            <div class="label">社融增量</div>
            <div class="value">{summary["afre_flow_wanyiyuan"]:.2f} 万亿元</div>
          </div>
        </div>
        <div class="chart">
          <img src="{IMAGE_PATH.name}" alt="存市比趋势图" />
        </div>
        <div class="links">
          <a href="{IMAGE_PATH.name}">打开趋势图 PNG</a>
          <a href="{CSV_PATH.name}">打开明细 CSV</a>
          <a href="{MONEY_SUPPLY_CSV.name}">打开货币供应量 CSV</a>
          <a href="{PMI_CSV.name}">打开 PMI CSV</a>
          <a href="{SOCIAL_FINANCING_CSV.name}">打开社融 CSV</a>
          <a href="{UNIFIED_IMAGE.name}">打开 M1-M2 可比同比剪刀差图</a>
          <a href="{UNIFIED_CSV.name}">打开 M1-M2 可比同比剪刀差 CSV</a>
          <a href="{SUMMARY_JSON.name}">打开摘要 JSON</a>
        </div>
      </section>
    </main>
  </body>
</html>
"""
    (OUTPUT_DIR / "index.html").write_text(html, encoding="utf-8")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = load_summary(SUMMARY_JSON)

    shutil.copy2(IMAGE_PATH, OUTPUT_DIR / IMAGE_PATH.name)
    shutil.copy2(CSV_PATH, OUTPUT_DIR / CSV_PATH.name)
    shutil.copy2(MONEY_SUPPLY_CSV, OUTPUT_DIR / MONEY_SUPPLY_CSV.name)
    shutil.copy2(PMI_CSV, OUTPUT_DIR / PMI_CSV.name)
    shutil.copy2(SOCIAL_FINANCING_CSV, OUTPUT_DIR / SOCIAL_FINANCING_CSV.name)
    shutil.copy2(UNIFIED_CSV, OUTPUT_DIR / UNIFIED_CSV.name)
    shutil.copy2(UNIFIED_IMAGE, OUTPUT_DIR / UNIFIED_IMAGE.name)
    shutil.copy2(UNIFIED_SUMMARY_JSON, OUTPUT_DIR / UNIFIED_SUMMARY_JSON.name)
    shutil.copy2(SUMMARY_JSON, OUTPUT_DIR / SUMMARY_JSON.name)
    (OUTPUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    write_index_html(summary)

    print(f"已生成 GitHub Pages 站点目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
