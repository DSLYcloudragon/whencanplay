"""后台的登录页换成我们自己的登录页。

Django admin 默认有一套独立的登录界面（/admin/login/），和站点的 /login/ 长得不一样。
这个子类把 admin 的 login() 覆盖掉：没登录访问后台时，直接跳去 /login/，
登录完再自动回到原来想去的后台页面。

于是全站只有一个登录入口。
"""

from django.contrib.admin import AdminSite
from django.shortcuts import redirect
from django.urls import reverse


class WhenCanPlayAdminSite(AdminSite):
    def login(self, request, extra_context=None):
        """admin 自己的登录页，一律改成跳我们的 /login/。

        Django 的 admin_view 会先把人送到 /admin/login/?next=...，
        所以这里要从 next 参数里把原本想去的地址捞出来，不能直接用当前路径。
        """
        target = request.GET.get('next') or reverse('admin:index')
        return redirect(f"{reverse('login')}?next={target}")


admin_site = WhenCanPlayAdminSite(name='admin')
