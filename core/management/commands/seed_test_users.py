"""创建几个测试用账号，方便登录 / 退出 / 多账号切换。

    python manage.py seed_test_users

重复执行是安全的：已存在的账号会把密码重置回下面的值。
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

PASSWORD = 'TestPass2026'

TEST_USERS = [
    ('test1@example.com', '测试一号'),
    ('test2@example.com', '测试二号'),
    ('test3@example.com', '测试三号'),
]


class Command(BaseCommand):
    help = '创建测试账号（邮箱 + 固定密码）'

    def handle(self, *args, **options):
        User = get_user_model()
        created = 0

        for email, nickname in TEST_USERS:
            user, is_new = User.objects.get_or_create(
                username=email,
                defaults={'email': email, 'nickname': nickname},
            )
            user.email = email
            user.nickname = nickname
            user.set_password(PASSWORD)
            user.save()
            if is_new:
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f'新建 {created} 个，共 {len(TEST_USERS)} 个测试账号。统一密码：{PASSWORD}\n'
        ))
        for email, nickname in TEST_USERS:
            self.stdout.write(f'  {email:22} {nickname}')
