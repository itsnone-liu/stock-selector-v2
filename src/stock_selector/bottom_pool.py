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
        """按最新数据更新各事件状态。daily_loader(code)->DataFrame|None。"""
        frame = self.load()
        if frame.empty:
            return {"checked": 0}
        counts = {"invalidated": 0, "expired": 0, "checked": 0}
        for i, row in frame.iterrows():
            if row["状态"] != "active":
                continue
            counts["checked"] += 1
            daily = daily_loader(row["代码"])
            if daily is None or daily.empty:
                continue
            after = daily[daily.index > pd.Timestamp(row["事件日"])]
            event_low = float(row["事件日最低"])
            broken = after[after["close"] < event_low]
            if not broken.empty:
                frame.at[i, "状态"] = "invalidated"
                frame.at[i, "失效日"] = str(broken.index[0].date())
                counts["invalidated"] += 1
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
