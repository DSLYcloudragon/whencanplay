from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import Availability
from .services import DAY_NAMES


class RegisterForm(forms.Form):
    """注册：邮箱 + 昵称 + 密码，就这几个框。

    邮箱直接当登录名（username），不发任何验证邮件 —— 这是产品里明确的设计取舍：
    用简化注册换取「点开链接就能参与」的低门槛。
    """

    email = forms.EmailField(
        label='邮箱',
        widget=forms.EmailInput(attrs={
            'placeholder': 'you@example.com',
            'autocomplete': 'email',
            'autofocus': True,
        }),
    )
    nickname = forms.CharField(
        label='昵称',
        max_length=32,
        widget=forms.TextInput(attrs={
            'placeholder': '群里显示的名字',
            'autocomplete': 'nickname',
        }),
    )
    password1 = forms.CharField(
        label='密码',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text='至少 8 位',
    )
    password2 = forms.CharField(
        label='再输一次',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if get_user_model().objects.filter(username=email).exists():
            raise ValidationError('这个邮箱已经注册过了')
        return email

    def clean_nickname(self):
        return self.cleaned_data['nickname'].strip()

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')

        if p1 and p2 and p1 != p2:
            self.add_error('password2', '两次输入的密码不一样')
        elif p1:
            try:
                validate_password(p1)
            except ValidationError as exc:
                self.add_error('password1', exc)

        return cleaned

    def save(self):
        User = get_user_model()
        return User.objects.create_user(
            username=self.cleaned_data['email'],
            email=self.cleaned_data['email'],
            nickname=self.cleaned_data['nickname'],
            password=self.cleaned_data['password1'],
        )


class GroupCreateForm(forms.Form):
    name = forms.CharField(
        label='群名',
        max_length=64,
        widget=forms.TextInput(attrs={'placeholder': '比如：深夜食堂', 'autofocus': True}),
    )


class JoinGroupForm(forms.Form):
    invite_code = forms.CharField(
        label='邀请码',
        max_length=12,
        widget=forms.TextInput(attrs={'placeholder': '8 位邀请码', 'autofocus': True}),
    )

    def clean_invite_code(self):
        from .models import Group

        code = self.cleaned_data['invite_code'].strip().lower()
        if not Group.objects.filter(invite_code=code).exists():
            raise ValidationError('没有这个邀请码，检查一下有没有输错')
        return code


class AvailabilityForm(forms.Form):
    """加一段空闲时间。

    开始和结束都填到半小时。结束早于开始表示跨到第二天凌晨。

    周期是 7 天时，第一个字段是「星期」；周期不是 7 天时，它是「第几天」。
    具体选项在 __init__ 里按用户的周期生成。
    """

    weekday = forms.ChoiceField(label='星期', choices=[])
    start = forms.TimeField(
        label='从',
        widget=forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
        initial='20:00',
    )
    end = forms.TimeField(
        label='到',
        widget=forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
        initial='23:00',
        help_text='比开始时间早就表示跨到第二天凌晨',
    )
    state = forms.ChoiceField(
        label='状态',
        choices=Availability.STATE_CHOICES,
        initial=Availability.STATE_FREE,
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        n = (getattr(user, 'cycle_days', None) or 7) if user is not None else 7
        if n == 7:
            self.fields['weekday'].label = '星期'
            self.fields['weekday'].choices = [
                (i, name) for i, name in enumerate(DAY_NAMES)
            ]
        else:
            self.fields['weekday'].label = '第几天'
            self.fields['weekday'].choices = [(i, f'第 {i + 1} 天') for i in range(n)]

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start')
        end = cleaned.get('end')

        for field, value in (('start', start), ('end', end)):
            if value and value.minute not in (0, 30):
                self.add_error(field, '时间要填到整点或半点')

        if start and end and start == end:
            self.add_error('end', '开始和结束不能是同一时刻')

        return cleaned


# 周期天数的预设，选项文字要让人看得懂
CYCLE_PRESETS = [
    (7, '7 天 —— 每周固定（最常见）'),
    (14, '14 天 —— 大小周 / 单双周'),
    (4, '4 天 —— 四天一循环的排班'),
    (8, '8 天 —— 白白小夜小夜大夜大夜休休'),
    (21, '21 天 —— 三周一循环'),
    (28, '28 天 —— 四周一循环'),
]


class CycleForm(forms.Form):
    """设置作息周期：多少天一个循环，以及这一轮的第 1 天是哪天。"""

    cycle_days = forms.ChoiceField(label='作息周期', choices=[])
    cycle_anchor = forms.DateField(
        label='这一轮的第 1 天',
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        help_text='留空表示从本周一算起。周期为 7 天时不用填。',
    )

    def __init__(self, *args, current=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = list(CYCLE_PRESETS)
        if current and current not in [c[0] for c in choices]:
            choices.insert(0, (current, f'{current} 天 —— 当前设置'))
        self.fields['cycle_days'].choices = choices
