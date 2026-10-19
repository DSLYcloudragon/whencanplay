from urllib.parse import quote

from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services
from .forms import AvailabilityForm, GroupCreateForm, JoinGroupForm, RegisterForm
from .models import Availability, Group, Membership


def index(request):
    """首页：列出已有的群；登录后还能看到「我加入的群」。"""
    groups = Group.objects.all()[:12]

    my_groups = []
    if request.user.is_authenticated:
        my_groups = Group.objects.filter(memberships__user=request.user).distinct()

    return render(request, 'core/index.html', {
        'groups': groups,
        'my_groups': my_groups,
    })


def group_heatmap(request, code):
    """某个群的周时间热力图。"""
    group = get_object_or_404(Group, code=code)

    rows = services.build_rows_with_mine(group, request.user)
    summary = services.build_summary(group, rows)
    days = [{'index': i, 'name': n} for i, n in enumerate(services.DAY_NAMES)]

    is_member = False
    if request.user.is_authenticated:
        is_member = Membership.objects.filter(user=request.user, group=group).exists()

    return render(request, 'core/heatmap.html', {
        'group': group,
        'rows': rows,
        'days': days,
        'summary': summary,
        'is_member': is_member,
    })


def _cell_json(cell, hour):
    """把一格整理成前端要的形状。"""
    return {
        'count': cell['count'],
        'names_text': cell['names_text'],
        'level': cell['level'],
        'my_state': cell['my_state'],
        'shown': cell['shown'],
        'extra': cell['extra'],
        'day': cell['day'],
        'hour': hour,
    }


@login_required
@require_POST
def mark_hour(request, code):
    """在热力图上标时间：点一格，或者按住拖一段。

    只在成员之间可用 —— 没入群的人看得见格子，但点不动。
    """
    group = get_object_or_404(Group, code=code)

    if not Membership.objects.filter(user=request.user, group=group).exists():
        return JsonResponse({'ok': False, 'error': '你还没加入这个群'}, status=403)

    try:
        weekday = int(request.POST['weekday'])
        start_hour = int(request.POST['hour_start'])
        end_hour = int(request.POST['hour_end'])
    except (KeyError, ValueError):
        return JsonResponse({'ok': False, 'error': '参数不对'}, status=400)

    if not (0 <= weekday <= 6 and 0 <= start_hour < 24 and start_hour < end_hour <= 24):
        return JsonResponse({'ok': False, 'error': '参数不对'}, status=400)

    state = request.POST.get('state') or None
    allowed = (None, Availability.STATE_FREE, Availability.STATE_BUSY)
    if state not in allowed:
        return JsonResponse({'ok': False, 'error': '状态不对'}, status=400)

    # scope=group 只改这个群；其余情况写人级默认，对所有群生效
    target_group = group if request.POST.get('scope') == 'group' else None
    services.set_span(request.user, target_group, weekday, start_hour, end_hour, state)

    rows = services.build_rows_with_mine(group, request.user)
    cells = [
        _cell_json(rows[hour]['cells'][weekday], hour)
        for hour in range(start_hour, end_hour)
    ]

    return JsonResponse({'ok': True, 'cells': cells})


def old_heatmap(request):
    """旧地址 /heatmap/，跳到一个真实存在的群，免得旧链接失效。"""
    group = Group.objects.order_by('created_at').first()
    if group is None:
        raise Http404('还没有任何群，先跑：python manage.py seed_demo')
    return redirect('group_heatmap', code=group.code)


def register(request):
    """注册。邮箱只当登录名，不发验证邮件；注册成功直接登录。"""
    if request.user.is_authenticated:
        return redirect('index')

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            return redirect('index')
    else:
        form = RegisterForm()

    return render(request, 'core/register.html', {'form': form})


@login_required
def group_create(request):
    """建群：生成链接标识和邀请码，创建者自动成为群主。"""
    if request.method == 'POST':
        form = GroupCreateForm(request.POST)
        if form.is_valid():
            group = Group.objects.create(
                name=form.cleaned_data['name'],
                code=Group.new_code(),
                invite_code=Group.new_invite_code(),
            )
            Membership.objects.create(
                user=request.user,
                group=group,
                role=Membership.ROLE_OWNER,
            )
            return redirect('group_heatmap', code=group.code)
    else:
        form = GroupCreateForm()

    return render(request, 'core/group_new.html', {'form': form})


def group_join(request):
    """凭邀请码入群。

    没登录也能先填码：提交时把码塞进 next，登录完再回来，不用重背那串随机字符。
    """
    if not request.user.is_authenticated:
        code = ''
        if request.method == 'POST':
            code = (request.POST.get('invite_code') or '').strip()
        target = reverse('group_join')
        if code:
            target += '?code=' + quote(code)
        return redirect(f"{reverse('login')}?next={quote(target)}")

    if request.method == 'POST':
        form = JoinGroupForm(request.POST)
        if form.is_valid():
            group = Group.objects.get(invite_code=form.cleaned_data['invite_code'])
            Membership.objects.get_or_create(
                user=request.user,
                group=group,
                defaults={'role': Membership.ROLE_MEMBER},
            )
            return redirect('group_heatmap', code=group.code)
    else:
        form = JoinGroupForm(initial={'invite_code': request.GET.get('code', '')})

    return render(request, 'core/group_join.html', {'form': form})


@login_required
def my_schedule(request):
    """我的每周作息（人级默认）。

    这里填的区间对所有群生效；某个群想不一样，后面再做群级覆盖的界面。
    """
    if request.method == 'POST':
        form = AvailabilityForm(request.POST)
        if form.is_valid():
            Availability.objects.create(
                user=request.user,
                group=None,
                weekday=int(form.cleaned_data['weekday']),
                start=form.cleaned_data['start'],
                end=form.cleaned_data['end'],
                state=form.cleaned_data['state'],
                week_key='',
            )
            return redirect('my_schedule')
    else:
        form = AvailabilityForm()

    ranges = list(
        Availability.objects
        .filter(user=request.user, group__isnull=True, week_key='')
        .order_by('weekday', 'start')
    )

    days = []
    for index, name in enumerate(services.DAY_NAMES):
        days.append({
            'index': index,
            'name': name,
            'ranges': [r for r in ranges if r.weekday == index],
        })

    return render(request, 'core/schedule.html', {
        'form': form,
        'days': days,
        'total': len(ranges),
    })


@login_required
def delete_range(request, pk):
    """删掉自己的一段空闲时间。只允许 POST，避免被链接误删。"""
    item = get_object_or_404(Availability, pk=pk, user=request.user)
    if request.method == 'POST':
        item.delete()
    return redirect('my_schedule')
