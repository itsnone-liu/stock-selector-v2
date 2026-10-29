#!/usr/bin/env python3
"""CF-IS Phase 2A descriptive event windows; stdlib only, no collection.

Relative weeks count observed trading-week rows, NOT elapsed calendar weeks.
A non-observed event ISO week is retained as an explicitly missing anchor row.
All dates/timestamps are interpreted in Asia/Shanghai (fixed UTC+08:00).
"""
import argparse
import bisect
import csv
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL_TZ = timezone(timedelta(hours=8))
REQUIRED = ("event_id", "title", "event_type", "source_url", "published_at",
            "first_usable_at", "effective_at", "event_cluster_id", "evidence_status")
DATE_FIELDS = ("published_at", "first_usable_at", "effective_at")
ELIGIBILITY = {"PRE": "PRE_EVENT_CONTEXT", "EVENT": "MIXED_EVENT_WEEK_NOT_PREKNOWN",
               "POST": "POST_EVENT_OBSERVATION_NOT_ENTRY_SIGNAL"}
CALENDARS = (("calendar_2023_q2", "2023-04-03", "2023-06-30"),
             ("calendar_2024_q2", "2024-04-01", "2024-06-28"))
META_FIELDS = ["window_id", "window_kind", "phase", "rel_observed_week",
               "feature_eligibility", "pre_context_availability", "coverage_status", "event_iso_week",
               "row_status", "window_complete", "pre_weeks_observed",
               "post_weeks_observed", "missing_pre_weeks", "missing_post_weeks",
               "event_week_observed", "window_status", "cluster_event_count",
               "cluster_event_ids", "cluster_events_json", "event_metadata_json",
               "calendar_start", "calendar_end", "comparison_status"]


def parse_event_date(value, label):
    """Require ISO dates or timezone-aware ISO timestamps; never guess timezones."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: missing date")
    try:
        if len(value) == 10:
            return datetime.combine(date.fromisoformat(value), datetime.min.time(), LOCAL_TZ)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timestamp must carry timezone")
        return parsed.astimezone(LOCAL_TZ)
    except ValueError as exc:
        raise ValueError(f"{label}: invalid ISO date/time {value!r}: {exc}") from exc


def iso_week(day):
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def week_start(week):
    try:
        parsed = date.fromisocalendar(int(week[:4]), int(week[6:]), 1)
        if iso_week(parsed) != week:
            raise ValueError("non-canonical week")
        return parsed
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid ISO week: {week!r}") from exc


def load_weekly(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        if not {"week", "week_end", "days_obs"} <= set(fields):
            raise ValueError("weekly table requires week, week_end, days_obs")
        if len(fields) != len(set(fields)):
            raise ValueError("duplicate weekly columns")
        if set(fields) & (set(META_FIELDS) | set(REQUIRED)):
            raise ValueError("weekly columns collide with window/event metadata")
        rows = list(reader)
    if not rows:
        raise ValueError("weekly table is empty")
    previous = None
    for row in rows:
        start = week_start(row["week"])
        if previous is not None and start <= previous:
            raise ValueError("weekly rows must be strictly increasing and unique")
        previous = start
        try:
            end = datetime.strptime(row["week_end"], "%Y%m%d").date()
            days = int(row["days_obs"])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid week_end/days_obs for {row['week']}") from exc
        if iso_week(end) != row["week"] or not 1 <= days <= 7:
            raise ValueError(f"inconsistent week_end/days_obs for {row['week']}")
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"malformed CSV row for {row['week']}")
    return fields, rows


def load_events(path):
    with Path(path).open(encoding="utf-8") as stream:
        ledger = json.load(stream)
    if not isinstance(ledger, dict) or not isinstance(ledger.get("events"), list):
        raise ValueError("ledger must contain an events list")
    if ledger.get("coverage_status") != "seed_not_exhaustive":
        raise ValueError("coverage_status must be seed_not_exhaustive")
    ids, clusters = set(), {}
    for event in ledger["events"]:
        if not isinstance(event, dict):
            raise ValueError("event must be an object")
        for field in REQUIRED:
            if not isinstance(event.get(field), str) or not event[field].strip():
                raise ValueError(f"event {event.get('event_id', '?')}: missing {field}")
        if event["event_id"] in ids:
            raise ValueError(f"duplicate event_id: {event['event_id']}")
        ids.add(event["event_id"])
        dates = {key: parse_event_date(event[key], f"{event['event_id']}.{key}")
                 for key in DATE_FIELDS}
        if dates["first_usable_at"] < dates["published_at"]:
            raise ValueError(f"{event['event_id']}: first_usable_at precedes published_at")
        if not event["source_url"].startswith(("https://", "http://")):
            raise ValueError(f"{event['event_id']}: source_url must be HTTP(S)")
        clusters.setdefault(event["event_cluster_id"], []).append(event)
    groups = []
    for cluster, members in sorted(clusters.items()):
        # One descriptive window per cluster. Later announcements remain provenance,
        # not extra independent samples or knowledge at the representative's anchor.
        members.sort(key=lambda e: (parse_event_date(e["first_usable_at"], "first_usable_at"),
                                    e["event_id"]))
        groups.append((members[0], members))
    return ledger, groups


def pre_availability(row, event, phase):
    if phase != "PRE":
        return "NOT_PRE_CONTEXT"
    if str(row.get("availability_unknown", "0")).lower() not in ("0", "false"):
        return "UNKNOWN_ATOMIC_AVAILABILITY"
    if not row.get("usable_at"):
        return "MISSING_USABLE_AT"
    try:
        usable = parse_event_date(row["usable_at"], "weekly.usable_at")
    except ValueError:
        return "INVALID_USABLE_AT"
    anchor = parse_event_date(event["first_usable_at"], "first_usable_at")
    return "USABLE_BEFORE_EVENT" if usable < anchor else "LATE_OR_AT_EVENT_NOT_PREKNOWN"


def build_windows(weekly, ledger, groups):
    starts = [week_start(row["week"]) for row in weekly]
    output = []
    for event, members in groups:
        anchor = week_start(iso_week(parse_event_date(event["first_usable_at"], "first_usable_at")))
        position = bisect.bisect_left(starts, anchor)
        observed = position < len(starts) and starts[position] == anchor
        pre = weekly[max(0, position - 8):position]
        post_start = position + int(observed)
        post = weekly[post_start:post_start + 12]
        status = []
        if len(pre) < 8:
            status.append("LEFT_TRUNCATED")
        if not observed:
            status.append("MISSING_EVENT_WEEK")
        if len(post) < 12:
            status.append("RIGHT_CENSORED")
        base = {**{key: event[key] for key in REQUIRED},
                "window_id": f"event:{event['event_cluster_id']}", "window_kind": "EVENT",
                "coverage_status": ledger["coverage_status"], "event_iso_week": iso_week(anchor),
                "window_complete": str(not status).lower(), "window_status": "|".join(status) or "COMPLETE",
                "pre_weeks_observed": len(pre), "post_weeks_observed": len(post),
                "missing_pre_weeks": 8 - len(pre), "missing_post_weeks": 12 - len(post),
                "event_week_observed": str(observed).lower(), "cluster_event_count": len(members),
                "cluster_event_ids": json.dumps([e["event_id"] for e in members], ensure_ascii=False),
                "cluster_events_json": json.dumps(members, ensure_ascii=False, sort_keys=True),
                "event_metadata_json": json.dumps(event, ensure_ascii=False, sort_keys=True)}
        segments = [(row, "PRE", index - len(pre)) for index, row in enumerate(pre)]
        segments.append((weekly[position] if observed else {}, "EVENT", 0))
        segments.extend((row, "POST", index + 1) for index, row in enumerate(post))
        for row, phase, relative in segments:
            output.append({**row, **base, "phase": phase, "rel_observed_week": relative,
                           "feature_eligibility": ELIGIBILITY[phase],
                           "pre_context_availability": pre_availability(row, event, phase),
                           "row_status": "OBSERVED" if row else "MISSING_EVENT_WEEK"})
    for name, begin, end in CALENDARS:
        first, last = date.fromisoformat(begin), date.fromisoformat(end)
        selected = [r for r in weekly if first <= datetime.strptime(r["week_end"], "%Y%m%d").date() <= last]
        for row in selected:
            output.append({**row, "window_id": name, "window_kind": "CALENDAR_COMPARISON",
                           "phase": "CALENDAR_COMPARISON", "rel_observed_week": "",
                           "feature_eligibility": "CALENDAR_COMPARISON_NOT_EVENT_SCREENED",
                           "coverage_status": ledger["coverage_status"], "row_status": "OBSERVED",
                           "calendar_start": begin, "calendar_end": end,
                           "comparison_status": "PRESET_QUARTER_NOT_EVENT_SCREENED_NOT_EVENT_FREE_CONTROL"})
    return output


def write_summary(path, ledger, groups, rows, weekly):
    anchors = [r for r in rows if r["phase"] == "EVENT"]
    lines = ["# CF-IS IS2A — 事件连续观察窗", "",
             "## 方法与解释边界", "",
             "- 本报告及 CSV 仅为描述性案例组织；禁止因果推断，禁止把事件/重叠窗当独立样本。",
             "- 源台账覆盖状态：`seed_not_exhaustive`（非穷尽）；缺席不能解释为无事件。",
             "- first_usable_at 按 UTC+08:00 的 ISO 周锚定；日期精度不补造日内可用时点。",
             "- 相对周按已观测交易周连续行计数，跳过休市周；前 8 周 / 事件周 / 后 12 周。",
             "- 若事件 ISO 周不在周表，保留缺失 EVENT 占位行，不把下一交易周偷换成事件周。",
             "- 完整窗只表示行数齐全，不证明周表底层字段完整或逐字段 point-in-time 合规。",
             "- PRE 另逐行核对 usable_at < first_usable_at；缺失、原子可用性未知、晚于/等于事件分别标记。",
             "  该检查不把 timing_scope 中排除的回溯 episodes 字段升级为 PIT 特征。",
             f"- PRE 可用性核查：{dict(Counter(r['pre_context_availability'] for r in rows if r['phase'] == 'PRE'))}",
             f"- 台账选样声明：{ledger.get('selection_policy', '未提供；仅为非穷尽探索案例。')}",
             "- PRE=`PRE_EVENT_CONTEXT`，只表示事前周表背景，事件元数据是回溯关联，不能作事前特征。",
             "- EVENT=`MIXED_EVENT_WEEK_NOT_PREKNOWN`，整周混合事件前后，不能把 EVENT 整周当已知事件输入。",
             "- POST=`POST_EVENT_OBSERVATION_NOT_ENTRY_SIGNAL`，只作事后观察，不是入场信号。",
             "- 同 cluster 只保留最早 first_usable_at（同刻按 event_id 排序）的代表窗；",
             "  cluster_events_json 保留所有来源，仅供回溯审计，后续公告不是锚点时的已知信息。",
             "- effective_at 可早于/晚于可用日期，不用于替代 first_usable_at；日期缺失或先可用后发布则拒绝。",
             "", "## 覆盖与完整窗", "",
             f"- 周表：{weekly[0]['week']} .. {weekly[-1]['week']}，{len(weekly)} 个观测交易周。",
             f"- 台账事件 {len(ledger['events'])} 个；去重后 cluster 窗 {len(groups)} 个；"
             f"完整窗 {sum(r['window_complete'] == 'true' for r in anchors)} 个。",
             f"- 事件类型（源条目）：{dict(Counter(e['event_type'] for e in ledger['events']))}",
             f"- 证据状态（源条目）：{dict(Counter(e['evidence_status'] for e in ledger['events']))}", "",
             "|cluster / representative|event ISO week|PRE|POST|状态|合并条目数|",
             "|---|---|---:|---:|---|---:|"]
    for row in anchors:
        name = f"{row['event_cluster_id']} / {row['event_id']}".replace("|", "\\|")
        lines.append(f"|{name}|{row['event_iso_week']}|{row['pre_weeks_observed']}|"
                     f"{row['post_weeks_observed']}|{row['window_status']}|{row['cluster_event_count']}|")
    lines.extend(["", "## 固定日历比较窗（calendar comparison）", "",
                  "无事件筛选的预设季度片段；不是已证无事件对照，也不是匹配/随机对照。",
                  "即使包含已登记事件也保留，不依据事后走势或事件密度挑选。按 week_end 落入闭区间选行。", ""])
    for name, begin, end in CALENDARS:
        n = sum(row["window_id"] == name for row in rows)
        lines.append(f"- {name}: {begin} .. {end}，{n} 个观测周。")
    lines.extend(["", "不同 cluster 的窗口仍可能共享相同周表行，不能据去重宣称样本独立。",
                  "不估计事件效应、不打显著性标签、不产出交易信号。", ""])
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def run(weekly_path, events_path, output_path, summary_path):
    fields, weekly = load_weekly(weekly_path)
    ledger, groups = load_events(events_path)
    rows = build_windows(weekly, ledger, groups)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=META_FIELDS + list(REQUIRED) + fields)
        writer.writeheader()
        writer.writerows(rows)
    write_summary(summary_path, ledger, groups, rows, weekly)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weekly", "--csv", type=Path, default=ROOT / "data/cfis/weekly_full_202201_202610.csv")
    parser.add_argument("--events", "--seed", type=Path, default=ROOT / "docs/research/cfis/macro_events_seed.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cfis/is2a_event_windows.csv")
    parser.add_argument("--summary", type=Path, default=ROOT / "docs/research/cfis/IS2A_EVENT_WINDOWS.md")
    args = parser.parse_args()
    try:
        rows = run(args.weekly, args.events, args.output, args.summary)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"Wrote {len(rows)} descriptive rows to {args.output}; summary: {args.summary}")


if __name__ == "__main__":
    main()
