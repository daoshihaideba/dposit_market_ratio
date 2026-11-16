import json
import re
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


IMAGE_NAMES = {"头条": "headlines.png", "全球半导体": "global-chips.png", "中国半导体": "china-chips.png"}
INK = "#122436"
MUTED = "#4f6575"
TEAL = "#0e6a61"
IMPACT_COLORS = {
    "偏正向": ("#18583f", "#e1f4e9"),
    "偏负向": ("#902e3d", "#fbe6e9"),
    "多空交织": ("#77501a", "#fff0d5"),
    "中性": ("#35596e", "#e7eff4"),
    "待确认": ("#35596e", "#e7eff4"),
}
WIDTH = 960
MARGIN = 48
CONTENT_WIDTH = WIDTH - MARGIN * 2


def news_font(size: int, bold: bool = False):
    weight = "Bold" if bold else "Regular"
    apple_weight = "Medium" if bold else "Light"
    for path, index in (
        (f"/usr/share/fonts/opentype/noto/NotoSansCJK-{weight}.ttc", 2),
        (f"/System/Library/Fonts/STHeiti {apple_weight}.ttc", 0),
        ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 0),
    ):
        if Path(path).is_file():
            return ImageFont.truetype(path, size, index=index)
    raise RuntimeError("图片需要 Noto Sans CJK 中文字体")


def wrap_text(value, font, width):
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9./%+-]*|.", value)
    lines = []
    line = ""
    for token in tokens:
        for part in token if font.getlength(token) > width else (token,):
            if line and font.getlength(line + part) > width:
                lines.append(line.rstrip())
                line = part.lstrip()
            else:
                line += part
    if line:
        lines.append(line.rstrip())
    return lines


def write_image(path: Path, metadata: dict, section: dict):
    section_font = news_font(54, bold=True)
    headline_font = news_font(37, bold=True)
    body_font = news_font(31)
    meta_font = news_font(25)
    blocks = []

    def add(value, font, color, gap, *, x=MARGIN, width=CONTENT_WIDTH):
        if value:
            blocks.append((wrap_text(value, font, width), font, color, gap, x))

    add("新闻日报", meta_font, TEAL, 12)
    add(section["title"], section_font, INK, 14)
    add(metadata["period"], meta_font, MUTED, 13)
    add(section["subtitle"], meta_font, MUTED, 12)
    if not section["items"]:
        add("本期暂无符合条件的新闻。", body_font, INK, 20)
    for index, item in enumerate(section["items"], 1):
        blocks.append(None)
        add(f"{index:02d}  {item['title']}", headline_font, INK, 10)
        add(item["summary"], body_font, MUTED, 10)
        if "impact" in item:
            color, background = IMPACT_COLORS[item["impact"]]
            add(f"159516 · {item['impact']}", meta_font, (color, background), 12)
            add(item["reason"], body_font, INK, 10)
        add(item["source"], meta_font, MUTED, 14)
    if metadata["notes"]:
        blocks.append(None)
        add(" ".join(metadata["notes"]), meta_font, MUTED, 0)

    height = MARGIN * 2 + sum(
        29 if block is None else len(block[0]) * (block[1].size + 13) + block[3]
        for block in blocks
    )
    image = Image.new("RGB", (WIDTH, height), "#f8fbfa")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 9), fill=TEAL)
    y = MARGIN
    for block in blocks:
        if block is None:
            draw.line((MARGIN, y + 6, WIDTH - MARGIN, y + 6), fill="#ccdcd8", width=2)
            y += 29
            continue
        lines, font, color, gap, x = block
        if isinstance(color, tuple):
            color, background = color
            right = x + font.getlength(lines[0]) + 28
            draw.rounded_rectangle((x, y, right, y + font.size + 11), radius=10, fill=background)
            x += 14
        for line in lines:
            draw.text((x, y + 4), line, font=font, fill=color, anchor="lt")
            y += font.size + 13
        y += gap
    image.save(path, optimize=True)


def write_news_pages(output_dir: Path, metadata: dict, sections: list[dict], fund_link: str):
    output_dir.mkdir(parents=True, exist_ok=True)
    body = []
    for section in sections:
        write_image(output_dir / section["image"], metadata, section)
        title = escape(section["title"])
        image = section["image"]
        body.append(f'<section><h2>{title}</h2><p><a href="{image}">打开原图</a></p><ol>')
        for item in section["items"]:
            url = escape(item["url"], quote=True)
            body.append(f'<li><a href="{url}">{escape(item["title"])}</a> · {escape(item["source"])}</li>')
        if not section["items"]:
            body.append("<li>本期暂无符合条件的新闻。</li>")
        body.append("</ol></section>")
    title = escape(metadata["title"])
    period = escape(metadata["period"])
    html = f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{font: 17px/1.6 system-ui,sans-serif; background: #f8fbfa; color: #122436;
       max-width: 720px; margin: auto; padding: 1rem;}}
a {{color: #0e6a61;}} li {{margin-block: .65rem;}} section {{margin-top: 2rem;}}
</style>
<main><h1>{title}</h1><p>{period}</p>
{"".join(body)}
<p><a href="{fund_link}">查看 159516 基金资料</a></p>
</main></html>
"""
    (output_dir / "index.html").write_text(html, encoding="utf-8")
    (output_dir / "edition.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
