"""假数据 —— 只用于第 3 步先把热力图做出来。

这里的数据形状是故意照着 Availability 模型编的：
一条记录 = 谁 + 周几 + 从几点 + 到几点。

将来接真数据库时，只要让 build_rows() 从 Availability 查询出同样的结构，
heatmap.html 一行都不用改。

跨午夜用超过 24 的小时数表示：周五 22 点到凌晨 3 点，写成 (4, 22, 27)。
"""

MEMBERS = [
    {
        'nickname': '阿杰',
        'slots': [
            (0, 20, 24), (1, 20, 24), (2, 20, 24), (3, 20, 24),
            (4, 20, 27), (5, 10, 27), (6, 10, 24),
        ],
    },
    {
        'nickname': '小林',
        'slots': [
            (0, 21, 25), (1, 21, 25), (3, 21, 25), (4, 21, 26),
            (5, 14, 24), (6, 14, 24),
        ],
    },
    {
        'nickname': '老王',
        'slots': [
            (5, 10, 22), (6, 10, 22),
        ],
    },
    {
        'nickname': '雪梨',
        'slots': [
            (0, 19, 23), (1, 19, 23), (2, 19, 23), (3, 19, 23), (4, 19, 24),
            (5, 9, 24),
        ],
    },
    {
        'nickname': '大鹏',
        'slots': [
            (4, 22, 27), (5, 20, 28), (6, 20, 24),
        ],
    },
    {
        'nickname': '阿珍',
        'slots': [
            (0, 12, 14), (0, 20, 22), (1, 12, 14), (1, 20, 22),
            (2, 12, 14), (2, 20, 22), (3, 12, 14), (3, 20, 22),
            (4, 12, 14), (5, 15, 23), (6, 15, 23),
        ],
    },
]

DAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

STACK_LIMIT = 3   # 格子里最多堆几个头像，多的收进 +N


def build_grid():
    """grid[weekday][hour] = [昵称, ...]"""
    grid = [[[] for _ in range(24)] for _ in range(7)]

    for member in MEMBERS:
        name = member['nickname']
        for weekday, start, end in member['slots']:
            # 把区间摊平成一个个小时，跨午夜的自然会落到第二天
            for absolute_hour in range(weekday * 24 + start, weekday * 24 + end):
                day_index, hour = divmod(absolute_hour, 24)
                grid[day_index % 7][hour].append(name)

    return grid


def build_rows():
    """按小时做行、星期做列 —— 和课表一样。

    每行是 {hour, cells}，每格是 {day, day_index, count, names, level, shown, extra}。
    level 是给 CSS 用的颜色档位（0~4），避免在模板里写判断。
    """
    grid = build_grid()
    rows = []

    for hour in range(24):
        cells = []
        for day_index, day_name in enumerate(DAY_NAMES):
            names = grid[day_index][hour]
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


def build_summary(rows):
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
        'members': len(MEMBERS),
        'covered_slots': covered,
        'busiest': best,
    }
