"""模板上下文处理器：所有页面都能拿到右上角「我的」菜单需要的数据。"""

from .models import Group


def nav_data(request):
    """当前用户加入的群，给下拉菜单用。

    放在上下文处理器里，是因为「我的」菜单出现在每个页面的右上角，
    而各页面的视图不一定都查了群。
    """
    groups = []
    if request.user.is_authenticated:
        groups = (
            Group.objects
            .filter(memberships__user=request.user)
            .distinct()
            .order_by('created_at')[:30]
        )
    return {'nav_groups': groups}
