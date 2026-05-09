from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.http import HttpResponse
from django.urls import path

from dominion import models
from dominion import admin_views


class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (("Dominion", {"fields": ("application_id", "api_key")}),)


class DomainAdmin(admin.ModelAdmin):
    list_display = ("title", "parent")
    search_fields = ("title",)

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            path(
                '<uuid:pk>/manage-roles-permissions/',
                self.admin_site.admin_view(admin_views.DomainManageRolesPermissionsView.as_view()),
                name="domain-manage-roles-permissions"),
        ]
        return my_urls + urls

    def save_model(self, request, obj, form, change):
        # Override because we have a custom manager that handles create
        if change:
            obj.save()
        else:
            new_obj = models.Domain.objects.create(**form.cleaned_data, owner=request.user)
            obj.pk = new_obj.pk


class RoleAdmin(admin.ModelAdmin):
    pass


class PermissionAdmin(admin.ModelAdmin):
    pass


class DomainRolePermissionAdmin(admin.ModelAdmin):
    list_display = ("domain", "role", "permission")
    search_fields = ("domain__title",)


class DomainPermissionAdmin(admin.ModelAdmin):
    pass


class UserDomainRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "domain", "role")
    search_fields = ("user__username", "domain__title")


class ResourceAdmin(admin.ModelAdmin):

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            path(
                '<uuid:pk>/manage-roles-permissions/',
                self.admin_site.admin_view(admin_views.ResourceManageRolesPermissionsView.as_view()),
                name="resource-manage-roles-permissions"),
        ]
        return my_urls + urls


class ResourceRolePermissionAdmin(admin.ModelAdmin):
    pass


class ResourcePermissionAdmin(admin.ModelAdmin):
    pass


class UserResourceRoleAdmin(admin.ModelAdmin):
    pass


admin.site.register(models.User, UserAdmin)
admin.site.register(models.Domain, DomainAdmin)
admin.site.register(models.Role, RoleAdmin)
admin.site.register(models.Permission, PermissionAdmin)
admin.site.register(models.DomainRolePermission, DomainRolePermissionAdmin)
admin.site.register(models.DomainPermission, DomainPermissionAdmin)
admin.site.register(models.UserDomainRole, UserDomainRoleAdmin)
admin.site.register(models.Resource, ResourceAdmin)
admin.site.register(models.ResourceRolePermission, ResourceRolePermissionAdmin)
admin.site.register(models.ResourcePermission, ResourcePermissionAdmin)
admin.site.register(models.UserResourceRole, UserResourceRoleAdmin)
