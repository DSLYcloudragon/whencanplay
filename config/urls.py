from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from core import views as core_views

urlpatterns = [
    path('admin/', admin.site.urls),

    # 页面
    path('', core_views.index, name='index'),
    path('g/<str:code>/', core_views.group_heatmap, name='group_heatmap'),
    path('heatmap/', core_views.old_heatmap, name='old_heatmap'),

    # 账号
    path('register/', core_views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
