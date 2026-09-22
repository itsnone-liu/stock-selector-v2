#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_qa_classify.py — classify 最早终点规则合成反例(二十轮; 验证本体函数).

run_condition_qa_coverage.classify v3+ 为模块级函数; 测试 import 真函数,
不另写公式。覆盖: 行政终止先于突破(若数据中出现必须被断言拦截或正确
排序——设计上行政截断日=日历尾>=一切日历内 bo/end, 断言验证此不变量)。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_condition_qa_coverage import classify  # noqa: E402


def main():
    ok = True
    # ① 窗内突破(事件)
    r = classify(i=100, bo_i=103, end_i=None, mkt=False, n_md=1000)
    print(f"① 窗内突破: {r}")
    if r != "event":
        print("   FAIL"); ok = False
    # ② 窗内市场退出(竞争)
    r = classify(i=100, bo_i=None, end_i=102, mkt=True, n_md=1000)
    print(f"② 窗内市场退出: {r}")
    if r != "competing":
        print("   FAIL"); ok = False
    # ③ 同日并发→竞争优先(保守)
    r = classify(i=100, bo_i=102, end_i=102, mkt=True, n_md=1000)
    print(f"③ 同日并发: {r}")
    if r != "competing":
        print("   FAIL"); ok = False
    # ④ 突破早于退出→事件
    r = classify(i=100, bo_i=101, end_i=104, mkt=True, n_md=1000)
    print(f"④ 突破更早: {r}")
    if r != "event":
        print("   FAIL"); ok = False
    # ⑤ 窗满(无任何终点)
    r = classify(i=100, bo_i=200, end_i=300, mkt=True, n_md=1000)
    print(f"⑤ 窗满: {r}")
    if r != "censor_window":
        print("   FAIL"); ok = False
    # ⑥ 行政型退出(data_end)在窗内, 无突破→行政删失
    r = classify(i=100, bo_i=200, end_i=104, mkt=False, n_md=1000)
    print(f"⑥ 行政型退出窗内: {r}")
    if r != "censor_admin":
        print("   FAIL"); ok = False
    # ⑦ 日历尾截断窗(i+5 超 n_md-1), 窗内无事件无退出→行政删失
    r = classify(i=998, bo_i=None, end_i=900, mkt=True, n_md=1000)
    print(f"⑦ 日历尾截断: {r}")
    if r != "censor_admin":
        print("   FAIL"); ok = False
    # ⑧ 合成反例: 行政截断先于突破——bo 在 (i, obs_last] 外即被 cands
    # 过滤(bo 只与 obs_last 比较); 若 bo_i <= obs_last 而 ad 逻辑漏排,
    # 运行时断言将拦截。此处验证: 突破在截断窗内→事件(不受行政影响)
    r = classify(i=998, bo_i=999, end_i=None, mkt=False, n_md=1000)
    print(f"⑧ 截断窗内突破: {r}")
    if r != "event":
        print("   FAIL"); ok = False
    # ⑨ 不变量: classify 到达 ad 分支时 bo/end 均不在截断窗内
    #    (由脚本内 assert 保证; 本测试确认正常路径不受影响)
    r = classify(i=997, bo_i=996, end_i=None, mkt=False, n_md=1000)  # bo 已过
    print(f"⑨ 突破已过(bo<=i): {r}")
    if r != "censor_admin":
        print("   FAIL"); ok = False
    print("ALL PASS" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
