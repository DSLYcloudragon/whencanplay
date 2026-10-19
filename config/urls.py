from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from core import views as core_views

urlpatterns = [
    path('admin/', admin.site.urls),

    # 页面
    path('', core_views.index, name='index'),
    path('me/', core_views.account, name='account'),
    path('g/<str:code>/', core_views.group_heatmap, name='group_heatmap'),
    path('g/<str:code>/mark/', core_views.mark_hour, name='mark_hour'),
    path('heatmap/', core_views.old_heatmap, name='old_heatmap'),

    # 群
    path('groups/new/', core_views.group_create, name='group_create'),
    path('groups/join/', core_views.group_join, name='group_join'),

    # 我的时间
    path('me/schedule/', core_views.my_schedule, name='my_schedule'),
    path('me/schedule/<int:pk>/delete/', core_views.delete_range, name='delete_range'),

    # 我的游戏
    path('me/games/', core_views.my_games, name='my_games'),

    # 账号
    path('register/', core_views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
