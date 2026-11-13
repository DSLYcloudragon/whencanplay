import datetime
from datetime import timedelta
from urllib.parse import quote

from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services
from .forms import CycleForm, GroupCreateForm, JoinGroupForm, RegisterForm
from .models import Availability, Game, Group, Membership, OwnedGame


def index(request):
    """首页。

    登录之后不再停在这里：直接跳到你上次看的群；没看过就跳第一个；一个群都没有就进账号菜单。
    未登录还是给一个落地页，说明这是什么。
    """
    if not request.user.is_authenticated:
        return render(request, 'core/index.html')

    # 1. 有置顶的群，直接进置顶的（最早的置顶优先）
    pinned = (Membership.objects
              .filter(user=request.user, is_pinned=True)
              .select_related('group')
              .order_by('joined_at')
              .first())
    if pinned:
        return redirect('group_heatmap', code=pinned.group.code)

    # 2. 没置顶，就回上次看的那个群
    last_code = request.session.get('last_group_code')
    if last_code:
        group = Group.objects.filter(
            code=last_code, memberships__user=request.user
        ).first()
        if group:
            return redirect('group_heatmap', code=group.code)

    # 3. 都没有，进第一个群
    first = (Group.objects
             .filter(memberships__user=request.user)
             .order_by('created_at')
             .first())
    if first:
        return redirect('group_heatmap', code=first.code)

    return redirect('account')


@login_required
def account(request):
    """账号菜单：我的群，以及填时间 / 选游戏 / 建群 / 加入群这些入口。"""
    memberships = (Membership.objects
                   .filter(user=request.user)
                   .select_related('group')
                   .order_by('-is_pinned', 'joined_at'))
    return render(request, 'core/account.html', {'memberships': memberships})


@login_required
@require_POST
def pin_group(request, code):
    """给群置顶 / 取消置顶。只认 POST，免得被链接误触。"""
    membership = get_object_or_404(
        Membership, user=request.user, group__code=code)
    membership.is_pinned = not membership.is_pinned
    membership.save(update_fields=['is_pinned'])

    next_url = _safe_next(request)
    return redirect(next_url or 'index')


def group_heatmap(request, code):
    """某个群的周时间热力图。

    可以用 ?game=ID 只看某一款游戏，用 ?week=2026-W46 看别的周。
    """
    group = get_object_or_404(Group, code=code)

    is_member = False
    if request.user.is_authenticated:
        is_member = Membership.objects.filter(user=request.user, group=group).exists()
        if is_member:
            # 记住在看哪个群，下次打开首页直接回来
            request.session['last_group_code'] = group.code

    games = services.group_game_list(group)

    selected_game = None
    raw_game = request.GET.get('game', '')
    if raw_game.isdigit():
        selected_game = Game.objects.filter(pk=int(raw_game)).first()

    # 看哪一周：默认本周，允许 ?week= 前后翻
    this_week = services.current_week_key()
    raw_week = request.GET.get('week', '')
    week_key = raw_week if services.is_week_key(raw_week) else this_week

    rows = services.build_rows_with_mine(
        group, request.user, week_key=week_key, only_game=selected_game)
    summary = services.build_summary(group, rows)
    summary['week_key'] = week_key
    days = [{'index': i, 'name': n} for i, n in enumerate(services.DAY_NAMES)]

    if selected_game is not None:
        summary['members'] = (
            OwnedGame.objects
            .filter(game=selected_game, user__memberships__group=group)
            .values('user').distinct().count()
        )

    return render(request, 'core/heatmap.html', {
        'group': group,
        'rows': rows,
        'days': days,
        'summary': summary,
        'is_member': is_member,
        'games': games,
        'selected_game': selected_game,
        'week_key': week_key,
        'this_week': this_week,
        'is_this_week': week_key == this_week,
        'week_label': services.week_label(week_key),
        'prev_week': services.shift_week(week_key, -1),
        'next_week': services.shift_week(week_key, 1),
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

    # 看的是哪一周。前端会带过来；不带就当本周。
    raw_week = request.POST.get('week', '')
    week_key = raw_week if services.is_week_key(raw_week) else services.current_week_key()

    # only_week=1 → 只覆盖这一周，循环规律不动
    only_week = request.POST.get('only_week') == '1'

    if only_week:
        services.set_span_week(
            request.user, target_group, week_key, weekday, start_hour, end_hour, state)
    else:
        # 点的是「这一周的星期几」，但存的是「周期第几天」——
        # 周期为 7 时两者相同；周期为 14 / 4 时要按日期换算。
        day = services.week_start(week_key) + timedelta(days=weekday)
        cycle_day = services.phase_of(request.user, day)
        services.set_span(
            request.user, target_group, cycle_day, start_hour, end_hour, state)

    rows = services.build_rows_with_mine(group, request.user, week_key=week_key)
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


def _safe_next(request, default=''):
    """取出 ?next= 并确认它是本站的相对路径，避免被人拿来跳到外站。"""
    nxt = request.GET.get('next') or request.POST.get('next') or ''
    if nxt.startswith('/') and not nxt.startswith('//'):
        return nxt
    return default


@login_required
def my_schedule(request):
    """我的每周作息（人级默认）。

    这里填的区间对所有群生效；某个群想不一样，后面再做群级覆盖的界面。

    支持 ?next=，这样从某个群的页面点进来后，还能原路返回那个群。
    """
    next_url = _safe_next(request)

    ranges = list(
        Availability.objects
        .filter(user=request.user, group__isnull=True, week_key='')
        .order_by('weekday', 'start')
    )

    cycle_days, anchor = services.cycle_of(request.user)

    days = []
    for index in range(cycle_days):
        days.append({
            'index': index,
            'name': services.day_name(request.user, index),
            'ranges': [r for r in ranges if r.weekday == index],
        })

    # 改过周期之后，落在当前周期之外的老数据也要列出来，不能"看不见但还在"
    orphans = [r for r in ranges if r.weekday >= cycle_days]

    # 周期网格：和群热力图一个样子，只是画的是自己的周期表
    states = services.cycle_states(request.user)
    grid_days = [
        {'index': i, 'name': services.day_name(request.user, i)}
        for i in range(cycle_days)
    ]
    grid_rows = []
    for hour in range(24):
        cells = []
        for i in range(cycle_days):
            st = states.get((i, hour))
            cells.append({
                'day': i,
                'state': st or '',
                'cls': 'is-free' if st == Availability.STATE_FREE
                else ('is-busy' if st == Availability.STATE_BUSY else ''),
            })
        grid_rows.append({'hour': hour, 'cells': cells})

    return render(request, 'core/schedule.html', {
        'days': days,
        'orphans': orphans,
        'total': len(ranges),
        'next_url': next_url,
        'cycle_days': cycle_days,
        'cycle_anchor': anchor,
        'grid_days': grid_days,
        'grid_rows': grid_rows,
    })


@login_required
@require_POST
def schedule_mark(request):
    """在「我的时间」的周期网格上点选：点一格或拖一段。"""
    try:
        day = int(request.POST['day'])
        start_hour = int(request.POST['hour_start'])
        end_hour = int(request.POST['hour_end'])
    except (KeyError, ValueError):
        return JsonResponse({'ok': False, 'error': '参数不对'}, status=400)

    n = services.cycle_of(request.user)[0]
    if not (0 <= day < n and 0 <= start_hour < 24 and start_hour < end_hour <= 24):
        return JsonResponse({'ok': False, 'error': '参数不对'}, status=400)

    state = request.POST.get('state') or None
    if state not in (None, Availability.STATE_FREE, Availability.STATE_BUSY):
        return JsonResponse({'ok': False, 'error': '状态不对'}, status=400)

    services.set_span(request.user, None, day, start_hour, end_hour, state)

    states = services.cycle_states(request.user)
    cells = [
        {'hour': hour, 'state': states.get((day, hour))}
        for hour in range(start_hour, end_hour)
    ]
    return JsonResponse({'ok': True, 'cells': cells})


@login_required
def my_cycle(request):
    """设置作息周期：多少天一个循环，以及这一轮的第 1 天是哪天。"""
    next_url = _safe_next(request)

    def back():
        url = reverse('my_schedule')
        if next_url:
            url += '?next=' + quote(next_url)
        return redirect(url)

    if request.method == 'POST':
        form = CycleForm(request.POST)
        if form.is_valid():
            request.user.cycle_days = int(form.cleaned_data['cycle_days'])
            request.user.cycle_anchor = form.cleaned_data['cycle_anchor'] or None
            request.user.save(update_fields=['cycle_days', 'cycle_anchor'])
            return back()
    else:
        form = CycleForm(initial={
            'cycle_days': request.user.cycle_days,
            'cycle_anchor': request.user.cycle_anchor,
        })

    # 存下来之后的周期长什么样，直接给人看 14 天
    cycle_days, _ = services.cycle_of(request.user)
    today = datetime.date.today()
    preview = []
    for offset in range(14):
        day = today + timedelta(days=offset)
        preview.append({
            'date': day,
            'label': services.day_name(request.user, services.phase_of(request.user, day)),
        })

    return render(request, 'core/cycle.html', {
        'form': form,
        'cycle_days': cycle_days,
        'preview': preview,
        'next_url': next_url,
    })


@login_required
def delete_range(request, pk):
    """删掉自己的一段空闲时间。只允许 POST，避免被链接误删。"""
    item = get_object_or_404(Availability, pk=pk, user=request.user)
    if request.method == 'POST':
        item.delete()

    url = reverse('my_schedule')
    next_url = _safe_next(request)
    if next_url:
        url += '?next=' + quote(next_url)
    return redirect(url)


@login_required
def my_games(request):
    """我的游戏库：勾出自己拥有的，再挑几款常玩的。

    提交时做「全量同步」：表里以表单为准，多退少补。
    这比一个个增删接口简单，也不会因为页面没刷新而出现脏数据。
    """
    games = list(Game.objects.all())
    next_url = _safe_next(request)

    if request.method == 'POST':
        owned_ids = set()
        for raw in request.POST.getlist('owned'):
            try:
                owned_ids.add(int(raw))
            except ValueError:
                pass

        fav_ids = set()
        for raw in request.POST.getlist('favorite'):
            try:
                fav_ids.add(int(raw))
            except ValueError:
                pass

        valid_ids = {g.pk for g in games}
        owned_ids &= valid_ids
        fav_ids &= owned_ids            # 常玩必然是拥有

        # 取消勾选的直接删
        OwnedGame.objects.filter(user=request.user).exclude(game_id__in=owned_ids).delete()

        for game_id in owned_ids:
            row, _ = OwnedGame.objects.get_or_create(
                user=request.user, game_id=game_id)
            want_fav = game_id in fav_ids
            if row.is_favorite != want_fav:
                row.is_favorite = want_fav
                row.save(update_fields=['is_favorite'])

        params = []
        if next_url:
            params.append('next=' + quote(next_url))
        params.append('saved=1')
        return redirect(reverse('my_games') + '?' + '&'.join(params))

    owned = {
        row.game_id: row.is_favorite
        for row in OwnedGame.objects.filter(user=request.user)
    }

    items = [
        {
            'game': game,
            'owned': game.pk in owned,
            'favorite': owned.get(game.pk, False),
        }
        for game in games
    ]

    return render(request, 'core/games.html', {
        'items': items,
        'owned_count': len(owned),
        'favorite_count': sum(1 for is_fav in owned.values() if is_fav),
        'next_url': next_url,
    })
