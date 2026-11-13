"""把一个人的作息导出成一串文本，另一个账号粘进去就能导入。

用途：换账号测试时不用重填十几分钟；以后也可以用来「抄朋友的作息」。

格式：FW1- 前缀 + base64url(zlib(json))，比纯 JSON 短很多。
只分享「人级」作息（对所有群生效的那层），群级覆盖和群绑定，换账号没有意义。
"""

import base64
import binascii
import datetime
import json
import zlib

from django.db import transaction

from . import services
from .models import Availability

PREFIX = 'FW1-'

MAX_ITEMS = 800          # 防止有人塞一个超大字符串
MAX_CODE_LEN = 20000


def _encode(payload):
    raw = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    blob = base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode('ascii')
    return PREFIX + blob.rstrip('=')


def _decode(code):
    text = (code or '').strip().replace('\n', '').replace('\r', '').replace(' ', '')
    if not text:
        raise ValueError('分享码是空的')
    if len(text) > MAX_CODE_LEN:
        raise ValueError('分享码太长了，可能不是有效内容')
    if not text.startswith(PREFIX):
        raise ValueError('这不像是一个分享码（应该以 FW1- 开头）')

    blob = text[len(PREFIX):]
    blob += '=' * (-len(blob) % 4)
    try:
        raw = zlib.decompress(base64.urlsafe_b64decode(blob.encode('ascii')))
    except (binascii.Error, zlib.error, ValueError):
        raise ValueError('分享码损坏了，检查一下有没有复制完整')

    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('分享码内容看不懂')

    if not isinstance(payload, dict) or payload.get('v') != 1:
        raise ValueError('分享码版本不支持')
    return payload


def export_schedule(user):
    """把这个人的作息导出成分享码。"""
    entries = (
        Availability.objects
        .filter(user=user, group__isnull=True)
        .order_by('weekday', 'start')
    )

    items = []
    for item in entries:
        items.append([
            item.weekday,
            item.start.hour * 60 + item.start.minute,
            item.end.hour * 60 + item.end.minute,
            'f' if item.state == Availability.STATE_FREE else 'b',
            item.week_key,
        ])

    payload = {
        'v': 1,
        'n': user.cycle_days or 7,
        'a': user.cycle_anchor.isoformat() if user.cycle_anchor else '',
        'i': items,
    }
    return _encode(payload)


def describe_schedule(user):
    """给页面显示的一句概况。"""
    qs = Availability.objects.filter(user=user, group__isnull=True)
    n, _ = services.cycle_of(user)
    return {
        'cycle_days': n,
        'total': qs.count(),
        'recurring': qs.filter(week_key='').count(),
        'single_week': qs.exclude(week_key='').count(),
    }


def import_schedule(user, code):
    """把分享码里的作息导入到这个人身上，**覆盖**原有的人级作息。

    返回 (段数, 周期天数)。
    """
    payload = _decode(code)

    try:
        cycle_days = int(payload.get('n') or 7)
    except (TypeError, ValueError):
        raise ValueError('周期天数不对')
    if not (1 <= cycle_days <= 365):
        raise ValueError('周期天数超出范围')

    anchor_text = payload.get('a') or ''
    anchor = None
    if anchor_text:
        try:
            anchor = datetime.date.fromisoformat(str(anchor_text))
        except ValueError:
            raise ValueError('周期起点日期格式不对')

    items = payload.get('i') or []
    if not isinstance(items, list):
        raise ValueError('作息内容格式不对')
    if len(items) > MAX_ITEMS:
        raise ValueError('作息内容太多了')

    rows = []
    for raw in items:
        if not isinstance(raw, list) or len(raw) != 5:
            raise ValueError('作息内容格式不对')
        day, start, end, state, week_key = raw

        if not isinstance(day, int) or not (0 <= day <= 364):
            raise ValueError('第几天超出范围')
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError('时间格式不对')
        if not (0 <= start <= 1439 and 0 < end <= 1440):
            raise ValueError('时间超出范围')
        if state not in ('f', 'b'):
            raise ValueError('状态不对')

        week_key = week_key or ''
        if week_key and not services.is_week_key(week_key):
            raise ValueError('单周标记格式不对')

        rows.append(Availability(
            user=user,
            group=None,
            weekday=day,
            start=datetime.time(start // 60, start % 60),
            end=datetime.time(end // 60, end % 60),
            state=Availability.STATE_FREE if state == 'f' else Availability.STATE_BUSY,
            week_key=week_key,
        ))

    with transaction.atomic():
        Availability.objects.filter(user=user, group__isnull=True).delete()
        Availability.objects.bulk_create(rows)

        user.cycle_days = cycle_days
        user.cycle_anchor = anchor
        user.save(update_fields=['cycle_days', 'cycle_anchor'])

    return len(rows), cycle_days
