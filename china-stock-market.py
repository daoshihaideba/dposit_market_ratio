import os
import time
from datetime import datetime

import pandas as pd
import tushare as ts


TOKEN_ENV_VAR = "TUSHARE_TOKEN"
START_DATE = os.getenv("START_DATE", "20150101")
END_DATE = os.getenv("END_DATE", datetime.today().strftime("%Y%m%d"))
OUTPUT_FILE = os.getenv("A_SHARE_OUTPUT_CSV", "a_share_month_end_total_mv.csv")
REQUEST_SLEEP_SECONDS = float(os.getenv("TUSHARE_REQUEST_SLEEP_SECONDS", "0.2"))
FILTER_A_SHARE_ONLY = os.getenv("FILTER_A_SHARE_ONLY", "true").lower() not in {"0", "false", "no"}

# 常见 A 股代码段，排除北交所和 B 股。
A_SHARE_PREFIXES = (
    "000",
    "001",
    "002",
    "003",
    "300",
    "301",
    "600",
    "601",
    "603",
    "605",
    "688",
    "689",
)


def get_pro_api():
    token = os.getenv(TOKEN_ENV_VAR)
    if not token:
        raise RuntimeError(
            f"缺少环境变量 {TOKEN_ENV_VAR}。"
            f"请先在 zsh 中执行: export {TOKEN_ENV_VAR}=你的_tushare_token"
        )

    ts.set_token(token)
    return ts.pro_api()


def get_month_end_trade_dates(pro, start_date: str, end_date: str) -> pd.DataFrame:
    """
    获取每个月最后一个交易日。
    如果当月尚未结束，则返回当月截至当前最新的交易日。
    """
    cal = pro.trade_cal(
        exchange="SSE",
        start_date=start_date,
        end_date=end_date,
        is_open="1",
    )

    if cal is None or cal.empty:
        raise ValueError("trade_cal 没有返回数据，请检查 token、积分权限或日期范围。")

    cal["cal_date"] = pd.to_datetime(cal["cal_date"], format="%Y%m%d")
    cal = cal.sort_values("cal_date").copy()
    cal["year_month"] = cal["cal_date"].dt.to_period("M")

    month_end = (
        cal.groupby("year_month", as_index=False)
        .agg(trade_date=("cal_date", "max"))
    )

    month_end["trade_date"] = month_end["trade_date"].dt.strftime("%Y%m%d")
    return month_end


def is_a_share_code(ts_code: str) -> bool:
    if not isinstance(ts_code, str):
        return False

    parts = ts_code.split(".")
    if len(parts) != 2:
        return False

    code, exchange = parts
    if exchange not in {"SH", "SZ"}:
        return False

    return code.startswith(A_SHARE_PREFIXES)


def fetch_total_market_value(pro, month_end_dates: pd.DataFrame) -> pd.DataFrame:
    """
    按月末交易日抓取 A 股总市值。
    返回单位：
    - total_mv_sum_wanyuan: 万元
    - total_mv_sum_yiyuan : 亿元
    - total_mv_sum_wanyiyuan: 万亿元
    """
    results = []

    for i, row in month_end_dates.iterrows():
        trade_date = row["trade_date"]
        print(f"[{i + 1}/{len(month_end_dates)}] 正在抓取 {trade_date} ...")

        try:
            df = pro.daily_basic(
                trade_date=trade_date,
                fields="ts_code,trade_date,total_mv",
            )
        except Exception as exc:
            print(f"  拉取失败: {trade_date}, error={exc}")
            time.sleep(1)
            continue

        if df is None or df.empty:
            print(f"  {trade_date} 无数据")
            continue

        if FILTER_A_SHARE_ONLY:
            df = df[df["ts_code"].map(is_a_share_code)].copy()

        df["total_mv"] = pd.to_numeric(df["total_mv"], errors="coerce").fillna(0)

        total_mv_sum_wanyuan = df["total_mv"].sum()
        total_mv_sum_yiyuan = total_mv_sum_wanyuan / 10000
        total_mv_sum_wanyiyuan = total_mv_sum_wanyuan / 100000000

        results.append(
            {
                "trade_date": trade_date,
                "stock_count": len(df),
                "total_mv_sum_wanyuan": total_mv_sum_wanyuan,
                "total_mv_sum_yiyuan": total_mv_sum_yiyuan,
                "total_mv_sum_wanyiyuan": total_mv_sum_wanyiyuan,
            }
        )

        time.sleep(REQUEST_SLEEP_SECONDS)

    result_df = pd.DataFrame(results)
    result_df["trade_date"] = pd.to_datetime(result_df["trade_date"], format="%Y%m%d")
    result_df = result_df.sort_values("trade_date").reset_index(drop=True)

    return result_df


def main():
    pro = get_pro_api()
    month_end_dates = get_month_end_trade_dates(pro, START_DATE, END_DATE)
    result_df = fetch_total_market_value(pro, month_end_dates)

    result_df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    print("\n完成，结果预览：")
    print(result_df.tail(12))
    print(f"\n已输出到: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
