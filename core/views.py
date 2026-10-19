from urllib.parse import quote

from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services
from .forms import AvailabilityForm, GroupCreateForm, JoinGroupForm, RegisterForm
from .models import Availability, Game, Group, Membership, OwnedGame


def index(request):
    """首页。

    登录之后不再停在这里：直接跳到你上次看的群；没看过就跳第一个；一个群都没有就进账号菜单。
    未登录还是给一个落地页，说明这是什么。
    """
    if not request.user.is_authenticated:
        return render(request, 'core/index.html')

    last_code = request.session.get('last_group_code')
    if last_code:
        group = Group.objects.filter(
            code=last_code, memberships__user=request.user
        ).first()
        if group:
            return redirect('group_heatmap', code=group.code)

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
    my_groups = Group.objects.filter(memberships__user=request.user).distinct()
    return render(request, 'core/account.html', {'my_groups': my_groups})


def group_heatmap(request, code):
    """某个群的周时间热力图。可以用 ?game=ID 只看某一款游戏。"""
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

    rows = services.build_rows_with_mine(group, request.user, only_game=selected_game)
    summary = services.build_summary(group, rows)
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

    def back_to_schedule():
        url = reverse('my_schedule')
        if next_url:
            url += '?next=' + quote(next_url)
        return redirect(url)

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
            return back_to_schedule()
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
