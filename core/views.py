from django.shortcuts import render

from . import mock


def index(request):
    """首页：先说明这是什么，再把人引到热力图。"""
    return render(request, 'core/index.html')


def heatmap(request):
    """群时间热力图。

    第 3 步：数据还是假的（core/mock.py）。
    第 5 步会把这里换成从 Availability 表查询，模板不动。
    """
    rows = mock.build_rows()
    summary = mock.build_summary(rows)
    days = [{'index': i, 'name': n} for i, n in enumerate(mock.DAY_NAMES)]

    return render(request, 'core/heatmap.html', {
        'rows': rows,
        'days': days,
        'summary': summary,
    })
