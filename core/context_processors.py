"""模板上下文处理器：所有页面都能拿到右上角「我的」菜单、以及页脚的备案号。"""

from django.conf import settings

from .models import Membership


def nav_data(request):
    """当前用户的成员关系（带置顶标记），给下拉菜单用。

    返回的是 Membership 而不是 Group，因为菜单里要显示「是否置顶」，
    也方便直接放置顶按钮。

    放在上下文处理器里，是因为「我的」菜单出现在每个页面的右上角，
    而各页面的视图不一定都查了群。
    """
    memberships = []
    if request.user.is_authenticated:
        memberships = list(
            Membership.objects
            .filter(user=request.user)
            .select_related('group')
            .order_by('-is_pinned', 'joined_at')
        )
    return {
        'nav_memberships': memberships,
        'icp_beian': getattr(settings, 'ICP_BEIAN', ''),
        'police_beian': getattr(settings, 'POLICE_BEIAN', ''),
    }
