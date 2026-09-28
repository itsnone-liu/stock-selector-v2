from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

from stock_selector.output import write_csv

COLUMNS = [
    "代码",
    "名称",
    "事件日",
    "事件日最低",
    "量倍数",
    "当日涨幅",
    "回撤深度",
    "平台位置",
    "状态",
    "失效日",
    "转化日",
    "更新时间",
]


class BottomPoolStore:
    """底部三倍量事件池：active / invalidated / expired / converted 状态机。

    - 失效：事件日之后任一收盘跌破事件日最低价；
    - 过期：超过 expiry_trading_days 个交易日未转化；
    - 转化：小金叉通道触发买点时回写。
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=COLUMNS)
        frame = pd.read_csv(self.path, dtype={"代码": str})
        if frame.empty:
            return pd.DataFrame(columns=COLUMNS)
        frame["代码"] = frame["代码"].astype(str).str.zfill(6)
        # CSV往返会把全空列推断为float64；状态/日期列必须保持字符串。
        for column in ("名称", "事件日", "状态", "失效日", "转化日", "更新时间"):
            if column in frame.columns:
                frame[column] = frame[column].fillna("").astype(str)
        return frame

    def append(self, events: list[dict]) -> None:
        if not events:
            return
        frame = self.load()
        incoming = pd.DataFrame(events)
        for column in COLUMNS:
            if column not in incoming.columns:
                incoming[column] = ""
        incoming = incoming[COLUMNS]
        combined = pd.concat([frame, incoming], ignore_index=True)
        combined = combined.drop_duplicates(["代码", "事件日"], keep="first")
        self._write(combined)

    def refresh(self, daily_loader, asof: datetime, expiry_trading_days: int = 60) -> dict[str, int]:
        """按最新数据更新各事件状态。daily_loader(code)->DataFrame|None。

        - 显式 asof 边界：只允许事件日之后、asof（含）之前的日线参与失效/过期
          判定（与信号管线同一约定）。数据源里 asof 之后的未来行不得驱动状态机——
          否则一次提前更新的数据文件会把 active 事件错误判成 invalidated/expired。
        - 最早终止事件优先（延迟刷新竞争语义）：破位与过期以各自**首次生效日**
          比较，较早者决定终态。若过期在第 61 个可见交易日已生效，而破位发生在
          第 70 日，则终态必须是 expired（本方法此前先扫全窗口破位，延迟刷新时
          会把本应 expired 的事件错标 invalidated）。同日同时触发时记 invalidated
          （破位是当日更具体的事件）。
        """
        frame = self.load()
        if frame.empty:
            return {"checked": 0}
        counts = {"invalidated": 0, "expired": 0, "checked": 0}
        asof_ts = pd.Timestamp(asof)
        for i, row in frame.iterrows():
            if row["状态"] != "active":
                continue
            counts["checked"] += 1
            daily = daily_loader(row["代码"])
            if daily is None or daily.empty:
                continue
            after = daily[(daily.index > pd.Timestamp(row["事件日"])) & (daily.index <= asof_ts)]
            event_low = float(row["事件日最低"])
            broken = after[after["close"] < event_low]
            # 过期生效位：事件后第 (expiry+1) 根可见日线（0-based 索引 = expiry）。
            expiry_pos = expiry_trading_days
            if not broken.empty:
                first_break_pos = int(after.index.get_loc(broken.index[0]))
                if first_break_pos <= expiry_pos:
                    frame.at[i, "状态"] = "invalidated"
                    frame.at[i, "失效日"] = str(broken.index[0].date())
                    counts["invalidated"] += 1
                    continue
                # 破位晚于过期生效日：过期已先行终止状态机。
                frame.at[i, "状态"] = "expired"
                counts["expired"] += 1
                continue
            if len(after) > expiry_trading_days:
                frame.at[i, "状态"] = "expired"
                counts["expired"] += 1
        frame["更新时间"] = asof.isoformat()
        self._write(frame)
        return counts

    def active(self) -> pd.DataFrame:
        frame = self.load()
        return frame[frame["状态"] == "active"].copy() if not frame.empty else frame

    def mark_converted(self, codes: list[str], day: date) -> None:
        frame = self.load()
        if frame.empty or not codes:
            return
        wanted = {str(code).zfill(6) for code in codes}
        mask = (frame["状态"] == "active") & frame["代码"].isin(wanted)
        frame.loc[mask, "状态"] = "converted"
        frame.loc[mask, "转化日"] = day.isoformat()
        self._write(frame)

    def _write(self, frame: pd.DataFrame) -> Path:
        return write_csv(frame, self.path)
