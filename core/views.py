from django.shortcuts import render


def index(request):
    """首页。

    第一步这里只做一件事：证明「路由 → 视图 → 模板」这条链路是通的。
    后面第 8 步，这个页面会换成真正的群时间热力图。
    """
    return render(request, 'core/index.html')
