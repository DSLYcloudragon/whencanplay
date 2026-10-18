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


def build_rows():
    """返回 7 行 × 24 列的结构，直接喂给模板。

    每一格是 {hour, count, names, level}。
    level 是给 CSS 用的颜色档位（0~4），避免在模板里写判断。
    """
    grid = [[[] for _ in range(24)] for _ in range(7)]

    for member in MEMBERS:
        name = member['nickname']
        for weekday, start, end in member['slots']:
            # 把区间摊平成一个个小时，跨午夜的自然会落到第二天
            for absolute_hour in range(weekday * 24 + start, weekday * 24 + end):
                day_index, hour = divmod(absolute_hour, 24)
                grid[day_index % 7][hour].append(name)

    rows = []
    for day_index, day_name in enumerate(DAY_NAMES):
        cells = []
        for hour in range(24):
            names = grid[day_index][hour]
            cells.append({
                'hour': hour,
                'count': len(names),
                'names': names,
                'names_text': '、'.join(names),
                'level': min(len(names), 4),
            })
        rows.append({'day': day_name, 'day_index': day_index, 'cells': cells})

    return rows


def build_summary(rows):
    """顶部那几个小数字。"""
    total_slots = 0
    best = {'count': 0, 'day': '', 'hour': 0}
    for row in rows:
        for cell in row['cells']:
            if cell['count']:
                total_slots += 1
            if cell['count'] > best['count']:
                best = {'count': cell['count'], 'day': row['day'], 'hour': cell['hour']}
    return {
        'members': len(MEMBERS),
        'covered_slots': total_slots,
        'busiest': best,
    }
