# GitHub Actions 配置说明

这个项目已经包含每日自动任务文件：

- `.github/workflows/daily_deposit_market_ratio.yml`
- `.github/workflows/daily_news_digest.yml`

你还需要在 GitHub 仓库里配置下面两个 Secrets：

- `TUSHARE_TOKEN`
  - 你的 Tushare Token
  - 必填，否则 A 股市值脚本无法运行
- `FTQQ_SENDKEY`
  - 你的方糖 / Server 酱 SendKey
  - 必填，否则不会推送消息给你

## 本地运行

```zsh
cd /Users/C5333286/Desktop/nexus
source venv/bin/activate
export TUSHARE_TOKEN=你的_tushare_token
python getDepositsofhouse.py
python china-stock-market.py
python build_deposit_market_ratio.py
```

如果你还想本地测试方糖推送：

```zsh
export FTQQ_SENDKEY=你的_sendkey
python notify_ftqq.py
```

## 24 小时新闻日报

每天北京时间 09:10，**Daily Deposit Market Ratio** 同时生成存市比日报和新闻日报，
将两份内容一起发布到 GitHub Pages，再用仓库的 `FTQQ_SENDKEY` 分别发送两条方糖消息。
新闻推送内嵌三张简体中文长图，分别是国内外要闻（最多 10 条）、全球芯片与半导体、
中国半导体与 159516。中国半导体新闻逐条标注影响方向及理由。消息附有原图和新闻原文链接。

可选的仓库 Secret `OPENAI_API_KEY` 用于中文标题、摘要、新闻排序和影响分析，模型默认为
`gpt-4.1-mini`，可用仓库变量 `NEWS_OPENAI_MODEL` 指定。未配置或模型请求失败时，
日报使用有中文标题的报道，统一转换为简体中文，按规则判断 159516 的方向。

在 GitHub Actions 手动运行 **Daily News Digest** 可下载 `chinese-news-digest` 预览，
其中有三张图片和原文链接页。手动运行 **Daily Deposit Market Ratio** 会发布并推送。
在本地可以安装 `requirements.txt` 中的依赖后运行 `python news_digest.py --preview`，
在 `news_preview/` 查看结果。Linux 上需要安装 Noto Sans CJK 中文字体。

## 产物文件

- `pboc_household_deposits.csv`：住户存款月度数据
- `a_share_month_end_total_mv.csv`：A 股月末市值数据
- `deposit_market_ratio.csv`：按月份对齐后的存市比明细
- `deposit_market_ratio_summary.json`：最新一期摘要
- `deposit_market_ratio_trend.png`：存市比趋势图

## GitHub Pages

这个 workflow 还会自动部署一个 GitHub Pages 页面，用来稳定承载图片和明细下载链接。

第一次使用时，建议你到仓库设置里确认：

- `Settings -> Pages`
- Build and deployment 选择 `GitHub Actions`
