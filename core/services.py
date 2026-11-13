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
from django.db.models import Count, Q

from .models import Availability, OwnedGame

DAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

STACK_LIMIT = 3  # 格子里最多堆几个头像，多的收进 +N

WEEK_MINUTES = 7 * 24 * 60  # 一周有多少分钟，用来做绝对坐标

# 默认周期起点：2026-01-05 是周一。
# 因为 (任意日期 - 任意周一) % 7 恒等于「星期几」，所以默认锚点保证
# 「周期 7 天」和旧的普通周表完全等价，老数据不用动。
MONDAY_EPOCH = datetime.date(2026, 1, 5)

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


def week_start(week_key):
    """2026-W42 → 那一周周一的日期。解析失败就退回本周。"""
    try:
        year, week = week_key.split('-W')
        return datetime.date.fromisocalendar(int(year), int(week), 1)
    except (ValueError, AttributeError):
        return week_start(current_week_key())


def cycle_of(user):
    """取这个人的作息周期：(天数, 起点日期)。

    周期是 7 的倍数时，把起点归一到那一周的周一 —— 这样「第几天」就等于「星期几」，
    老数据（按星期几存的）不用迁移也能算对。
    """
    n = getattr(user, 'cycle_days', None) or 7
    anchor = getattr(user, 'cycle_anchor', None) or MONDAY_EPOCH
    if n % 7 == 0:
        anchor = anchor - datetime.timedelta(days=anchor.weekday())
    return n, anchor


def phase_of(user, day):
    """某一天落在这个人周期里的第几天（0 起）。"""
    n, anchor = cycle_of(user)
    return (day - anchor).days % n


def day_name(user, cycle_day):
    """给人看的名字：周期 7 天时显示「周一」，否则显示「第 3 天」。"""
    n, _ = cycle_of(user)
    if n == 7 and 0 <= cycle_day < 7:
        return DAY_NAMES[cycle_day]
    return f'第 {cycle_day + 1} 天'


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


def _expand_entry(day, monday, entry):
    """把一条 Availability 摊到「这一周的第几列 × 第几个小时」。

    day 是这条记录生效的那一天；跨午夜的会溢到 day+1。
    """
    start_min = entry.start.hour * 60 + entry.start.minute
    end_min = entry.end.hour * 60 + entry.end.minute
    duration = (end_min - start_min) % 1440 or 1440   # 开始等于结束 = 整天

    begin = start_min
    finish = begin + duration
    base_col = (day - monday).days

    hour = begin // 60
    while hour * 60 < finish:
        if (hour + 1) * 60 > begin:
            # hour 是「从当天 0 点算起的第几个小时」，除以 24 得到跨到了第几天
            offset, hour_of_day = divmod(hour, 24)
            yield base_col + offset, hour_of_day
        hour += 1


def member_states(group, user, week_key):
    """某个成员这一周每一格的状态。返回 {(星期, 小时): 'free' / 'busy'}。

    周期不是 7 天时，同一个「星期」在不同周对应不同的周期第几天，
    所以要按**具体日期**去查，不能按星期直接查。
    """
    monday = week_start(week_key)
    n, _ = cycle_of(user)

    # 多取前一天：跨午夜的区间要从前一天溢进来
    phase_by_date = {}
    for offset in range(-1, 7):
        d = monday + datetime.timedelta(days=offset)
        phase_by_date[d] = phase_of(user, d)

    recurring_phases = {p for p in phase_by_date.values()}
    weekdays = set(recurring_phases) | set(range(7))

    entries = list(
        Availability.objects
        .filter(user=user)
        .filter(Q(group__isnull=True) | Q(group=group))
        .filter(Q(week_key='') | Q(week_key=week_key))
        .filter(weekday__in=weekdays)
    )

    by_phase = defaultdict(list)
    single_week = []
    for item in entries:
        if item.week_key:
            single_week.append(item)
        else:
            by_phase[item.weekday].append(item)

    layered = {}

    def put(col, hour, level, state):
        if not (0 <= col <= 6):
            return
        current = layered.get((col, hour))
        if current is None or level >= current[0]:
            layered[(col, hour)] = (level, state)

    # 循环作息：按日期落在周期第几天来取
    for day, phase in phase_by_date.items():
        for item in by_phase.get(phase, []):
            level = PRIORITY[(item.group_id is not None, False)]
            for col, hour in _expand_entry(day, monday, item):
                put(col, hour, level, item.state)

    # 单周例外：weekday 就是「这一周的星期几」，和周期无关
    for item in single_week:
        if not (0 <= item.weekday <= 6):
            continue
        day = monday + datetime.timedelta(days=item.weekday)
        level = PRIORITY[(item.group_id is not None, True)]
        for col, hour in _expand_entry(day, monday, item):
            put(col, hour, level, item.state)

    return {(col, hour): state for (col, hour), (_, state) in layered.items()}


def _group_members(group):
    return [
        (m.user, m.user.nickname or m.user.username)
        for m in group.memberships.select_related('user')
    ]


def build_grid(group, week_key=None, only_game=None):
    """{ (星期, 小时): [昵称, ...] }，只统计「有空」的人。

    「没空」是主动声明的不方便，和「没填过」在展示上一样，都不算可用人力。

    传了 only_game 就只算「拥有这款游戏的人」——这就是「看这款游戏什么时候人最齐」。
    """
    week_key = week_key or current_week_key()
    members = _group_members(group)

    if only_game is not None:
        member_ids = [user.pk for user, _ in members]
        owners = set(
            OwnedGame.objects
            .filter(game=only_game, user_id__in=member_ids)
            .values_list('user_id', flat=True)
        )
        members = [(user, name) for user, name in members if user.pk in owners]

    grid = defaultdict(list)
    for user, name in members:
        states = member_states(group, user, week_key)
        for cell, state in states.items():
            if state == Availability.STATE_FREE:
                grid[cell].append(name)

    return grid


def build_rows(group, week_key=None, only_game=None):
    """按小时做行、星期做列 —— 和课表一样。"""
    week_key = week_key or current_week_key()
    grid = build_grid(group, week_key, only_game=only_game)

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


def _abs_to_kwargs(segment, cycle_days=7):
    """绝对坐标 → 可以直接写进 Availability 的字段。

    跨到周期末尾会绕回第 0 天，所以这里取模。
    """
    begin, end, state = segment
    return {
        'weekday': (begin // 1440) % max(cycle_days, 1),
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


def set_span(user, group, cycle_day, start_hour, end_hour, state):
    """把「我」在周期第几天、哪几个小时的状态统一设成 state。

    start_hour 和 end_hour 是左闭右开的小时区间，比如 20 到 23 表示 20:00–23:00。
    一次点一格时传成同一个值（20, 21）；拖拽一段时传 (20, 23)。

    state 传 None 表示清除。group 传 None 表示写人级默认（对所有群生效）。

    注意 cycle_day 是「周期第几天」，不是星期几 —— 周期为 7 时两者相同。
    """
    if end_hour <= start_hour:
        end_hour = start_hour + 1

    n, _ = cycle_of(user)

    begin = cycle_day * 1440 + start_hour * 60
    end = cycle_day * 1440 + end_hour * 60

    entries = Availability.objects.filter(user=user, group=group, week_key='')
    segments = [_entry_to_abs(e) for e in entries]

    segments = _cut(segments, begin, end)
    if state:
        segments.append([begin, end, state])

    segments = _split_by_day(_normalize(segments))

    with transaction.atomic():
        Availability.objects.filter(user=user, group=group, week_key='').delete()
        Availability.objects.bulk_create([
            Availability(user=user, group=group, week_key='', **_abs_to_kwargs(segment, n))
            for segment in segments
        ])

    return state


def build_rows_with_mine(group, viewer, week_key=None, only_game=None):
    """在 build_rows 的基础上，给每一格标出「我自己」的状态。

    这样热力图上就能把你自己填的格子高亮出来，不然点完看不出效果。
    """
    week_key = week_key or current_week_key()
    rows = build_rows(group, week_key, only_game=only_game)

    mine = {}
    if viewer is not None and viewer.is_authenticated:
        mine = member_states(group, viewer, week_key)

    for row in rows:
        for cell in row['cells']:
            cell['my_state'] = mine.get((cell['day_index'], row['hour']))

    return rows


def cycle_states(user):
    """这个人整个周期、每一格的状态。返回 {(周期第几天, 小时): 'free' / 'busy'}。

    给「填我的时间」的网格用 —— 它和群热力图长得一样，但画的是自己的周期表。
    """
    n, _ = cycle_of(user)
    entries = Availability.objects.filter(user=user, group__isnull=True, week_key='')

    base = datetime.date(2026, 1, 5)   # 随便一个周一，只用来做坐标原点
    result = {}
    for item in entries:
        if not (0 <= item.weekday < n):
            continue
        day = base + datetime.timedelta(days=item.weekday)
        for col, hour in _expand_entry(day, base, item):
            result[(col % n, hour)] = item.state
    return result


def group_game_list(group):
    """这个群里大家拥有的游戏，按拥有者数量从多到少排。

    给热力图旁边的「大家能玩什么」面板用。
    """
    return list(
        OwnedGame.objects
        .filter(user__memberships__group=group)
        .values('game_id', 'game__name')
        .annotate(owner_count=Count('user', distinct=True))
        .order_by('-owner_count', 'game__name')
    )

