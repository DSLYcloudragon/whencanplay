from django.contrib import admin
from django.urls import path

from core import views as core_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', core_views.index, name='index'),
    path('g/<str:code>/', core_views.group_heatmap, name='group_heatmap'),
    path('heatmap/', core_views.old_heatmap, name='old_heatmap'),
]
