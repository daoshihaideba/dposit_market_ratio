# GitHub Actions 配置说明

这个项目已经包含每日自动任务文件：

- `.github/workflows/daily_deposit_market_ratio.yml`

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
