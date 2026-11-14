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

GitHub Actions 的 **Daily News Digest** 每天北京时间 09:25 计划运行，复用仓库的
`FTQQ_SENDKEY`。它会独立发送一条方糖消息，包含中国和国际头条（最多 10 条）、全球芯片与半导体新闻、
中国半导体新闻。每条中国半导体新闻都附有对 159516 的影响方向和理由，依据设备订单、
材料需求、国产替代等传导。每条新闻含发布时间和来源链接。

可选的仓库 Secret `OPENAI_API_KEY` 用于中文标题、摘要、新闻排序和影响分析，模型默认为
`gpt-4.1-mini`，可用仓库变量 `NEWS_OPENAI_MODEL` 指定。未配置或模型请求失败时，日报按公开 RSS
的标题和可用摘要自动筛选，沿用原文标题并使用规则判断 159516 的方向。

推送前可在 GitHub Actions 打开 **Daily News Digest → Run workflow**，保留默认勾选
**只生成日报预览（不发方糖）**，在任务日志查看结果。取消勾选即实际发送。
也可以用 `python news_digest.py --preview` 在本地预览。

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
