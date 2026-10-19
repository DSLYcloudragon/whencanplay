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

from django.db.models import Q

from .models import Availability

DAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

STACK_LIMIT = 3  # 格子里最多堆几个头像，多的收进 +N

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
