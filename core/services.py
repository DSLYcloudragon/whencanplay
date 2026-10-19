"""把 Availability 里的区间数据，聚合成热力图要用的二维表。

这是整个产品的计算核心。它只做三件事：
1. 找出这个群里所有人，对这个人，把所有适用的区间叠加起来
2. 把叠加后的结果摊平成「星期 × 小时」
3. 数出每一格有几个人

覆盖的优先级（数字越大越优先，同格子后写入的会盖掉先写入的）：

    人级 + 循环  <  人级 + 单周  <  群级 + 循环  <  群级 + 单周

也就是「越具体的越优先」：某个群的例外，压过你的一般作息。
"""

import datetime
from collections import defaultdict

from django.db import transaction
from django.db.models import Q

from .models import Availability

DAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

STACK_LIMIT = 3  # 格子里最多堆几个头像，多的收进 +N

WEEK_MINUTES = 7 * 24 * 60  # 一周有多少分钟，用来做绝对坐标

# (是否群级, 是否单周) -> 优先级
PRIORITY = {
    (False, False): 0,
    (False, True): 1,
    (True, False): 2,
    (True, True): 3,
}


def current_week_key(today=None):
    """这一周的标识，形如 2026-W42。"""
    day = today or datetime.date.today()
    iso = day.isocalendar()
    return f'{iso.year}-W{iso.week:02d}'


def interval_hours(weekday, start, end):
    """一段区间覆盖了哪些 (星期, 小时)。

    end <= start 表示跨到第二天凌晨，比如周六 22:00 → 02:00。
    """
    begin = weekday * 1440 + start.hour * 60 + start.minute
    finish = weekday * 1440 + end.hour * 60 + end.minute
    if finish <= begin:
        finish += 1440

    covered = set()
    hour = begin // 60
    while hour * 60 < finish:
        # 只保留确实和这一小时有重叠的
        if (hour + 1) * 60 > begin:
            covered.add(((hour // 24) % 7, hour % 24))
        hour += 1
    return covered


def member_states(group, user_id, week_key):
    """某个成员这一周每一格的状态。返回 {(星期, 小时): 'free' / 'maybe'}。"""
    entries = Availability.objects.filter(user_id=user_id).filter(
        Q(group__isnull=True) | Q(group=group)
    ).filter(
        Q(week_key='') | Q(week_key=week_key)
    )

    layered = {}
    for item in entries:
        level = PRIORITY[(item.group_id is not None, bool(item.week_key))]
        for cell in interval_hours(item.weekday, item.start, item.end):
            current = layered.get(cell)
            if current is None or level >= current[0]:
                layered[cell] = (level, item.state)

    return {cell: state for cell, (_, state) in layered.items()}


def _group_members(group):
    return [
        (m.user_id, m.user.nickname or m.user.username)
        for m in group.memberships.select_related('user')
    ]


def build_grid(group, week_key=None):
    """{ (星期, 小时): [昵称, ...] }，只统计有空和可能的人。"""
    week_key = week_key or current_week_key()
    grid = defaultdict(list)

    for user_id, name in _group_members(group):
        states = member_states(group, user_id, week_key)
        for cell, state in states.items():
            if state in (Availability.STATE_FREE, Availability.STATE_MAYBE):
                grid[cell].append(name)

    return grid


def build_rows(group, week_key=None):
    """按小时做行、星期做列 —— 和课表一样。"""
    week_key = week_key or current_week_key()
    grid = build_grid(group, week_key)

    rows = []
    for hour in range(24):
        cells = []
        for day_index, day_name in enumerate(DAY_NAMES):
            names = sorted(grid.get((day_index, hour), []))
            cells.append({
                'day': day_name,
                'day_index': day_index,
                'hour': hour,
                'count': len(names),
                'names_text': '、'.join(names),
                'level': min(len(names), 4),
                'shown': names[:STACK_LIMIT],
                'extra': max(len(names) - STACK_LIMIT, 0),
            })
        rows.append({'hour': hour, 'cells': cells})

    return rows


def build_summary(group, rows, week_key=None):
    """顶部那几个小数字。"""
    covered = 0
    best = {'count': 0, 'day': '', 'hour': 0}

    for row in rows:
        for cell in row['cells']:
            if cell['count']:
                covered += 1
            if cell['count'] > best['count']:
                best = {
                    'count': cell['count'],
                    'day': cell['day'],
                    'hour': row['hour'],
                }

    return {
        'members': group.memberships.count(),
        'covered_slots': covered,
        'busiest': best,
        'week_key': week_key or current_week_key(),
    }


# ---------------------------------------------------------------- 在热力图上点格子
#
# 数据存的是「区间」，但用户点的是「一小时」。所以每次点击要做四件事：
#   1. 把这个小时从已有的区间里挖掉（区间会被切成前后两段，精度保住）
#   2. 如果要标记，就补上一个一小时的区间
#   3. 把相邻且状态相同的段合并成一段
#   4. 跨天的地方切成两段（模型里一段区间最多跨一天，写回去才不会有歧义）


def _entry_to_abs(entry):
    """(weekday, start, end, state) → [开始分钟, 结束分钟, state]，一周内绝对坐标。"""
    start_min = entry.start.hour * 60 + entry.start.minute
    end_min = entry.end.hour * 60 + entry.end.minute
    begin = entry.weekday * 1440 + start_min
    duration = (end_min - start_min) % 1440 or 1440   # 开始等于结束 = 整天
    return [begin, begin + duration, entry.state]


def _abs_to_kwargs(segment):
    """绝对坐标 → 可以直接写进 Availability 的字段。"""
    begin, end, state = segment
    return {
        'weekday': begin // 1440,
        'start': datetime.time((begin % 1440) // 60, begin % 60),
        'end': datetime.time((end % 1440) // 60, end % 60),
        'state': state,
    }


def _cut(segments, cut_start, cut_end):
    """把所有区间在 [cut_start, cut_end) 这一段挖掉。"""
    result = []
    for begin, end, state in segments:
        if end <= cut_start or begin >= cut_end:
            result.append([begin, end, state])
            continue
        if begin < cut_start:
            result.append([begin, cut_start, state])
        if end > cut_end:
            result.append([cut_end, end, state])
    return result


def _normalize(segments):
    """同位置的段只留最后一个（后写的盖掉先写的），并合并相邻同状态的段。"""
    ordered = sorted(segments, key=lambda x: (x[0], x[1]))
    kept = []

    for begin, end, state in ordered:
        if end <= begin:
            continue
        trimmed = []
        for k_begin, k_end, k_state in kept:
            # 新的一段会盖掉重叠区域
            if k_end <= begin or k_begin >= end:
                trimmed.append([k_begin, k_end, k_state])
                continue
            if k_begin < begin:
                trimmed.append([k_begin, begin, k_state])
            if k_end > end:
                trimmed.append([end, k_end, k_state])
        trimmed.append([begin, end, state])
        kept = trimmed

    kept.sort(key=lambda x: x[0])

    merged = []
    for segment in kept:
        if merged and merged[-1][2] == segment[2] and merged[-1][1] == segment[0]:
            merged[-1][1] = segment[1]
        else:
            merged.append(segment)
    return merged


def _split_by_day(segments):
    """一段区间最多跨一天。超过一天的，在每天 00:00 处切开。"""
    result = []
    for begin, end, state in segments:
        cursor = begin
        while cursor < end:
            day_end = (cursor // 1440 + 1) * 1440
            stop = min(end, day_end)
            result.append([cursor, stop, state])
            cursor = stop
    return result


def set_hour(user, group, weekday, hour, state):
    """把「我」在某个小时的可用状态设成 state。

    state 传 None 表示清除。group 传 None 表示写人级默认（对所有群生效）。
    返回写入之后这个小时的状态。
    """
    begin = weekday * 1440 + hour * 60
    end = begin + 60

    entries = Availability.objects.filter(user=user, group=group, week_key='')
    segments = [_entry_to_abs(e) for e in entries]

    segments = _cut(segments, begin, end)
    if state:
        segments.append([begin, end, state])

    segments = _split_by_day(_normalize(segments))

    with transaction.atomic():
        Availability.objects.filter(user=user, group=group, week_key='').delete()
        Availability.objects.bulk_create([
            Availability(user=user, group=group, week_key='', **_abs_to_kwargs(segment))
            for segment in segments
        ])

    return state


def build_rows_with_mine(group, viewer, week_key=None):
    """在 build_rows 的基础上，给每一格标出「我自己」的状态。

    这样热力图上就能把你自己填的格子高亮出来，不然点完看不出效果。
    """
    week_key = week_key or current_week_key()
    rows = build_rows(group, week_key)

    mine = {}
    if viewer is not None and viewer.is_authenticated:
        mine = member_states(group, viewer.pk, week_key)

    for row in rows:
        for cell in row['cells']:
            cell['my_state'] = mine.get((cell['day_index'], row['hour']))

    return rows

