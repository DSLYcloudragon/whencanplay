from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .utils import random_code


class User(AbstractUser):
    """用户。

    登录用的账号是 username（我们拿邮箱填进去），
    nickname 才是群里显示的名字 —— 这两个是分开的。
    """

    nickname = models.CharField('昵称', max_length=32)
    steam_id = models.CharField('Steam ID', max_length=32, blank=True)
    avatar_url = models.URLField('头像地址', blank=True)

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = '用户'

    def __str__(self):
        return self.nickname or self.username


class Group(models.Model):
    """一个群。

    code 是公开的，出现在链接里，谁拿到都能看；
    invite_code 是私密的，用来入群，入群之后才能填写自己的信息。
    """

    name = models.CharField('群名', max_length=64)
    code = models.CharField('链接标识', max_length=12, unique=True, db_index=True)
    invite_code = models.CharField('邀请码', max_length=12, unique=True, db_index=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '群'
        verbose_name_plural = '群'
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @classmethod
    def new_code(cls):
        """生成一个没被占用的链接标识。"""
        for _ in range(30):
            code = random_code(8)
            if not cls.objects.filter(code=code).exists():
                return code
        raise RuntimeError('生成群标识失败：连续 30 次都撞上了')

    @classmethod
    def new_invite_code(cls):
        """生成一个没被占用的邀请码。"""
        for _ in range(30):
            code = random_code(8)
            if not cls.objects.filter(invite_code=code).exists():
                return code
        raise RuntimeError('生成邀请码失败：连续 30 次都撞上了')

    def owner(self):
        """当前的群主。没有 owner 字段，是因为成员关系只保留一份真相。"""
        m = self.memberships.filter(role=Membership.ROLE_OWNER).select_related('user').first()
        return m.user if m else None


class Membership(models.Model):
    """用户和群的关系。

    群主身份也走这张表（role='owner'），不在 Group 上另存一个 owner 字段，
    否则会出现「Group.owner 说是 A，成员表里说是 B」这种双份真相。
    """

    ROLE_OWNER = 'owner'
    ROLE_MEMBER = 'member'
    ROLE_CHOICES = [
        (ROLE_OWNER, '群主'),
        (ROLE_MEMBER, '成员'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name='用户',
    )
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name='群',
    )
    role = models.CharField('角色', max_length=10, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    joined_at = models.DateTimeField('加入时间', auto_now_add=True)

    class Meta:
        verbose_name = '成员关系'
        verbose_name_plural = '成员关系'
        constraints = [
            models.UniqueConstraint(fields=['user', 'group'], name='uniq_user_group'),
        ]

    def __str__(self):
        return f'{self.user} @ {self.group}（{self.get_role_display()}）'


class Availability(models.Model):
    """一段空闲时间。这是整个产品的心脏。

    两个可空维度组合出四种情况：

    1. group 为空、week_key 为空 —— 人级默认的循环周表（填一次，每周都算）
    2. group 有值、week_key 为空 —— 这个群的例外（这个群我不熬夜）
    3. week_key 有值、group 为空 —— 某一周的例外（这周出差）
    4. 两个都有值              —— 某个群的某一周的例外

    跨午夜：end 小于 start 就表示跨到第二天，例如 22:00 → 02:00。
    """

    STATE_FREE = 'free'
    STATE_MAYBE = 'maybe'
    STATE_BUSY = 'busy'
    STATE_CHOICES = [
        (STATE_FREE, '有空'),
        (STATE_MAYBE, '可能'),
        (STATE_BUSY, '没空'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='availabilities',
        verbose_name='用户',
    )
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='availabilities',
        verbose_name='群',
        help_text='留空表示人级默认，对所有群生效',
    )
    weekday = models.PositiveSmallIntegerField(
        '星期几',
        validators=[MinValueValidator(0), MaxValueValidator(6)],
        help_text='0 = 周一，6 = 周日',
    )
    start = models.TimeField('开始', help_text='填到半小时，比如 20:00 或 20:30')
    end = models.TimeField('结束', help_text='小于开始时间表示跨到第二天凌晨')
    state = models.CharField('状态', max_length=6, choices=STATE_CHOICES, default=STATE_FREE)
    week_key = models.CharField(
        '周次',
        max_length=8,
        blank=True,
        help_text='留空表示每周循环；填 2026-W42 这种表示只对这一周生效',
    )

    class Meta:
        verbose_name = '空闲时段'
        verbose_name_plural = '空闲时段'
        ordering = ['weekday', 'start']
        indexes = [
            models.Index(fields=['user', 'weekday']),
            models.Index(fields=['group', 'weekday']),
        ]

    def __str__(self):
        return f'{self.user} 周{self.weekday} {self.start}-{self.end}'


class Game(models.Model):
    """游戏。

    人数区间是最少 / 最佳 / 最多三个数，由维护者在后台填写 —— 这是编辑性知识，
    没有任何接口能自动拿到。
    """

    name = models.CharField('游戏名', max_length=100, unique=True)
    min_players = models.PositiveSmallIntegerField('最少人数', default=2)
    best_players = models.PositiveSmallIntegerField('最佳人数', default=4)
    max_players = models.PositiveSmallIntegerField('最多人数', default=8)

    platform = models.CharField('平台', max_length=32, default='PC')
    needs_mod = models.BooleanField('需要 Mod/插件', default=False)
    crossplay = models.BooleanField('支持跨平台', default=False)
    steam_appid = models.PositiveIntegerField('Steam AppID', null=True, blank=True)

    class Meta:
        verbose_name = '游戏'
        verbose_name_plural = '游戏'
        ordering = ['name']

    def __str__(self):
        return self.name


class OwnedGame(models.Model):
    """用户拥有的一款游戏。

    有这一行 = 拥有；is_favorite = 常玩。
    常玩是拥有的子集，所以不另建一张表。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_games',
        verbose_name='用户',
    )
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name='owners',
        verbose_name='游戏',
    )
    is_favorite = models.BooleanField(
        '常玩',
        default=False,
        help_text='只用来给结果排序，不影响能不能被匹配到',
    )

    class Meta:
        verbose_name = '拥有的游戏'
        verbose_name_plural = '拥有的游戏'
        constraints = [
            models.UniqueConstraint(fields=['user', 'game'], name='uniq_user_game'),
        ]

    def __str__(self):
        return f'{self.user} - {self.game}'
