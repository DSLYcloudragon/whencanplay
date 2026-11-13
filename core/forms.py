from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


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



class CycleForm(forms.Form):
    """设置作息周期：多少天一个循环，以及这一轮的第 1 天是哪天。

    周期天数随便填，不做预设限制 —— 只要自己能填得过来。
    """

    cycle_days = forms.IntegerField(
        label='多久一个循环（天）',
        min_value=1,
        max_value=365,
        widget=forms.NumberInput(attrs={
            'min': 1,
            'max': 365,
            'placeholder': '例如 7',
            'style': 'width:120px',
        }),
    )
    cycle_anchor = forms.DateField(
        label='这一轮的第 1 天',
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        help_text='留空表示从本周一算起。周期是 7 的倍数时会自动对齐到周一。',
    )
