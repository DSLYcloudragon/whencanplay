from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Availability, Game, Group, Membership, OwnedGame, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """在 Django 自带用户后台的基础上，加列我们自己的字段。"""

    list_display = ('username', 'nickname', 'steam_id', 'is_staff', 'date_joined')
    search_fields = ('username', 'nickname', 'steam_id')
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('开黑资料', {'fields': ('nickname', 'steam_id', 'avatar_url')}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ('开黑资料', {'fields': ('nickname', 'steam_id')}),
    )


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ('user',)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'invite_code', 'member_count', 'created_at')
    search_fields = ('name', 'code', 'invite_code')
    readonly_fields = ('created_at',)
    inlines = [MembershipInline]

    @admin.display(description='人数')
    def member_count(self, obj):
        return obj.memberships.count()


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'group', 'role', 'joined_at')
    list_filter = ('role', 'group')
    search_fields = ('user__nickname', 'user__username', 'group__name')
    autocomplete_fields = ('user', 'group')


@admin.register(Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ('user', 'weekday_display', 'start', 'end', 'state', 'group', 'week_key')
    list_filter = ('state', 'weekday', 'group')
    search_fields = ('user__nickname', 'user__username')
    autocomplete_fields = ('user', 'group')

    @admin.display(description='星期', ordering='weekday')
    def weekday_display(self, obj):
        return '周一周二周三周四周五周六周日'[obj.weekday * 2: obj.weekday * 2 + 2]


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'min_players', 'best_players', 'max_players',
        'platform', 'needs_mod', 'crossplay', 'owner_count',
    )
    list_filter = ('platform', 'needs_mod', 'crossplay')
    search_fields = ('name',)

    @admin.display(description='拥有者数')
    def owner_count(self, obj):
        return obj.owners.count()


@admin.register(OwnedGame)
class OwnedGameAdmin(admin.ModelAdmin):
    list_display = ('user', 'game', 'is_favorite')
    list_filter = ('is_favorite', 'game')
    search_fields = ('user__nickname', 'user__username', 'game__name')
    autocomplete_fields = ('user', 'game')
