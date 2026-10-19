"""创建一个演示用的群，塞进 6 个成员和他们的空闲时段。

用途：现在还没有「注册 / 建群 / 填时间」的界面，先用这个命令把数据造出来，
好让热力图有东西可显示。等第 5~8 步那些界面做好了，这个命令就只用来做演示数据。

    python manage.py seed_demo

重复执行是安全的：群和成员按固定标识复用，空闲时段每次重建。
"""

import datetime
import secrets
import string

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Availability, Group, Membership

# (昵称, 账号后缀, [(星期, 开始小时, 结束小时), ...])
# 结束小时可以大于 24，表示跨到第二天凌晨
DEMO_MEMBERS = [
    ('阿杰', 'ajie', [
        (0, 20, 24), (1, 20, 24), (2, 20, 24), (3, 20, 24),
        (4, 20, 27), (5, 10, 27), (6, 10, 24),
    ]),
    ('小林', 'xiaolin', [
        (0, 21, 25), (1, 21, 25), (3, 21, 25), (4, 21, 26),
        (5, 14, 24), (6, 14, 24),
    ]),
    ('老王', 'laowang', [
        (5, 10, 22), (6, 10, 22),
    ]),
    ('雪梨', 'xueli', [
        (0, 19, 23), (1, 19, 23), (2, 19, 23), (3, 19, 23), (4, 19, 24),
        (5, 9, 24),
    ]),
    ('大鹏', 'dapeng', [
        (4, 22, 27), (5, 20, 28), (6, 20, 24),
    ]),
    ('阿珍', 'azhen', [
        (0, 12, 14), (0, 20, 22), (1, 12, 14), (1, 20, 22),
        (2, 12, 14), (2, 20, 22), (3, 12, 14), (3, 20, 22),
        (4, 12, 14), (5, 15, 23), (6, 15, 23),
    ]),
]

GROUP_CODE = 'demo'
GROUP_NAME = '深夜食堂'


def _random_code(length=8):
    alphabet = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _to_time(hour):
    return datetime.time(hour % 24, 0)


class Command(BaseCommand):
    help = '创建演示用的群、成员和空闲时段'

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()

        group, _ = Group.objects.get_or_create(
            code=GROUP_CODE,
            defaults={
                'name': GROUP_NAME,
                'invite_code': _random_code(),
            },
        )

        created_users = 0
        for index, (nickname, slug, slots) in enumerate(DEMO_MEMBERS):
            username = f'demo_{slug}'
            user, is_new = User.objects.get_or_create(
                username=username,
                defaults={'nickname': nickname},
            )
            if is_new:
                user.nickname = nickname
                user.set_unusable_password()   # 演示账号不允许登录
                user.save()
                created_users += 1
            elif user.nickname != nickname:
                user.nickname = nickname
                user.save(update_fields=['nickname'])

            Membership.objects.get_or_create(
                user=user,
                group=group,
                defaults={
                    'role': Membership.ROLE_OWNER if index == 0 else Membership.ROLE_MEMBER,
                },
            )

        # 空闲时段每次重建，避免重复堆叠
        demo_users = User.objects.filter(username__startswith='demo_')
        Availability.objects.filter(user__in=demo_users, group__isnull=True).delete()
        Availability.objects.filter(user__in=demo_users, group=group).delete()

        count = 0
        for nickname, slug, slots in DEMO_MEMBERS:
            user = User.objects.get(username=f'demo_{slug}')
            Availability.objects.bulk_create([
                Availability(
                    user=user,
                    group=None,
                    weekday=weekday,
                    start=_to_time(start),
                    end=_to_time(end),
                    state=Availability.STATE_FREE,
                    week_key='',
                )
                for weekday, start, end in slots
            ])
            count += len(slots)

        # 故意造一条群级覆盖，用来验证「越具体的越优先」：
        # 阿杰在别的场合周日全天有空，但在这个群里周日不玩。
        ajie = User.objects.get(username='demo_ajie')
        Availability.objects.create(
            user=ajie,
            group=group,
            weekday=6,
            start=datetime.time(10, 0),
            end=datetime.time(23, 59),
            state=Availability.STATE_BUSY,
            week_key='',
        )

        self.stdout.write(self.style.SUCCESS(
            f'群：{group.name}（链接标识 {group.code}）\n'
            f'成员：{group.memberships.count()} 人（本次新建 {created_users} 人）\n'
            f'空闲区间：{count} 段 + 1 段群级覆盖\n'
            f'打开：/g/{group.code}/'
        ))
