from django.views.generic.edit import UpdateView

from dominion import admin_forms
from dominion import models
from dominion import utils


class DomainManageRolesPermissionsView(UpdateView):
    model = models.Domain
    template_name = "admin/dominion/domain/manage_roles_permissions.html"
    form_class = admin_forms.DomainManageRolesPermissionsForm

    def get_context_data(self, **kwargs):
        di = super().get_context_data()
        di["mapping"] = utils.domain_roles_permissions_mapping_sync(self.object)
        return di

    def get_success_url(self):
        # TODO: proper reverse
        return "/admin/dominion/domain/%s/change/" % self.object.id


class ResourceManageRolesPermissionsView(UpdateView):
    model = models.Resource
    template_name = "admin/dominion/resource/manage_roles_permissions.html"
    form_class = admin_forms.ResourceManageRolesPermissionsForm

    def get_context_data(self, **kwargs):
        di = super().get_context_data()
        di["mapping"] = utils.resource_roles_permissions_mapping_sync(self.object)
        return di

    def get_success_url(self):
        # TODO: proper reverse
        return "/admin/dominion/resource/%s/change/" % self.object.id

