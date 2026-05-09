from django.contrib.auth import get_user_model
from django.test import TestCase

from dominion import models, create_initial_data
from dominion.utils import user_has_permission_for_domain, user_has_permission_for_resource


"""
                                        Domain A                                                                Piet's root domain
                                        (jan has domain
                                        role Custom Viewer)
                                        (karen has domain role
                                        Manager)

             Resource A                  Resource B                    Resource C            Resource D             
             (inherit all)               (piet has resource                                  (allow Manager
                                         role Custom Viewer)                                 to Delete resource)

             Resource AA                 Resource BA                   Resource CA
             (no inherit on Read)        (piet has inherited           (piet has resource
                                         resource role Custom Viewer)  role Custom Viewer)


Domain AA                                                                       Domain AB
                                                                                (allow Manager
                                                                                to Delete domain)
Domain AAA
(koos has domain role Owner)
"""


class BaseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        create_initial_data()

        # Users
        User = get_user_model()
        owner = User.objects.create(username="owner")
        owner.set_password("password")
        owner.save()
        piet = User.objects.create(username="piet")
        piet.set_password("password")
        piet.save()
        jan = User.objects.create(username="jan")
        jan.set_password("password")
        jan.save()
        karen = User.objects.create(username="karen")
        karen.set_password("password")
        karen.save()
        koos = User.objects.create(username="koos")
        koos.set_password("password")
        koos.save()

        # Domains
        domaina = models.Domain.objects.create(title="Domain A", owner=owner)
        domainaa = models.Domain.objects.create(title="Domain AA", owner=owner, parent=domaina)
        domainab = models.Domain.objects.create(title="Domain AB", owner=owner, parent=domaina)
        domainaaa = models.Domain.objects.create(title="Domain AAA", owner=koos, parent=domainaa)

        domaina_resourcea = models.Resource.objects.create(urn="domaina:resourcea", domain=domaina, owner=owner)
        domaina_resourceaa = models.Resource.objects.create(
            urn="domaina:resourceaa", parent=domaina_resourcea, domain=domaina, owner=owner
        )
        domaina_resourceb = models.Resource.objects.create(urn="domaina:resourceb", domain=domaina, owner=owner)
        domaina_resourceba = models.Resource.objects.create(
            urn="domaina:resourceba", parent=domaina_resourceb, domain=domaina, owner=owner
        )
        domaina_resourcec = models.Resource.objects.create(urn="domaina:resourcec", domain=domaina, owner=owner)
        domaina_resourceca = models.Resource.objects.create(
            urn="domaina:resourceca", parent=domaina_resourcec, domain=domaina, owner=owner
        )
        domainaa_resourcea = models.Resource.objects.create(
            urn="domainaa:resourcea", domain=domainaa, owner=owner
        )
        domaina_resourced = models.Resource.objects.create(urn="domaina:resourced", domain=domaina, owner=owner)
        deletable_domain = models.Domain.objects.create(title="Deletable domain", owner=owner)
        undeletable_domain = models.Domain.objects.create(title="Undeletable domain", owner=owner)
        undeletable_domain_resource = models.Resource.objects.create(
            urn="undeletable_domain:resource", domain=undeletable_domain, owner=owner
        )
        piets_root_domain = models.Domain.objects.create(title="Piet's root domain", owner=piet)

        # Custom Viewer role needed by Jan
        permission_read = models.Permission.objects.get(code="read")
        role_customviewer = models.Role.objects.create(code="customviewer", title="Custom Viewer")
        models.DomainRolePermission.objects.create(
            domain=domaina, role=role_customviewer, permission=permission_read
        )
        models.UserDomainRole.objects.create(user=jan, domain=domaina, role=role_customviewer)

        # Strip Read permission acquisition from domaina_resourceaa
        models.ResourcePermission.objects.create(
            resource=domaina_resourceaa, permission=permission_read, inherit=False
        )

        # Piet gets Custom Viewer role on domaina_resourceb and domaina_resourceca
        models.UserResourceRole.objects.create(
            user=piet, resource=domaina_resourceb, role=role_customviewer
        )
        models.UserResourceRole.objects.create(
            user=piet, resource=domaina_resourceca, role=role_customviewer
        )

        # Karen get Manager role on domaina
        role_manager = models.Role.objects.get(code="manager")
        models.UserDomainRole.objects.create(
            user=karen, domain=domaina, role=role_manager
        )

        # Set Manager role on domaina_resourced and domainab to be able to delete
        permission_delete = models.Permission.objects.get(code="delete")
        models.ResourceRolePermission.objects.create(resource=domaina_resourced, role=role_manager, permission=permission_delete)
        models.DomainRolePermission.objects.create(domain=domainab, role=role_manager, permission=permission_delete)

        # Aliases
        cls.owner = owner
        cls.piet = piet
        cls.jan = jan
        cls.karen = karen
        cls.domaina = domaina
        cls.domainaa = domainaa
        cls.domainab = domainab
        cls.domainaaa = domainaaa
        cls.domaina_resourcea = domaina_resourcea
        cls.domaina_resourceaa = domaina_resourceaa
        cls.domaina_resourceb = domaina_resourceb
        cls.domaina_resourceba = domaina_resourceba
        cls.domaina_resourceca = domaina_resourceca
        cls.domainaa_resourcea = domainaa_resourcea
        cls.domaina_resourced = domaina_resourced
        cls.deletable_domain = deletable_domain
        cls.undeletable_domain = undeletable_domain
        cls.piets_root_domain = piets_root_domain
