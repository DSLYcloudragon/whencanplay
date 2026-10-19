from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from . import services
from .models import Group


def index(request):
    """首页：说明这是什么，并列出已有的群。"""
    groups = Group.objects.all()[:12]
    return render(request, 'core/index.html', {'groups': groups})


def group_heatmap(request, code):
    """某个群的周时间热力图。

    数据来自 Availability 表，不再是写死的假数据。
    """
    group = get_object_or_404(Group, code=code)

    rows = services.build_rows(group)
    summary = services.build_summary(group, rows)
    days = [{'index': i, 'name': n} for i, n in enumerate(services.DAY_NAMES)]

    return render(request, 'core/heatmap.html', {
        'group': group,
        'rows': rows,
        'days': days,
        'summary': summary,
    })


def old_heatmap(request):
    """旧地址 /heatmap/，跳到一个真实存在的群，免得旧链接失效。"""
    group = Group.objects.order_by('created_at').first()
    if group is None:
        raise Http404('还没有任何群，先跑：python manage.py seed_demo')
    return redirect('group_heatmap', code=group.code)
