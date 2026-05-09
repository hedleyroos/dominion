# Data migration: initialise Domain.descendant_count and Domain.resource_count
# from the current rows in the database.

from django.db import migrations


def populate_domain_counters(apps, schema_editor):
    Domain = apps.get_model("dominion", "Domain")
    Resource = apps.get_model("dominion", "Resource")

    # descendant_count: total domains that share this domain as their root
    # (including the root itself, because filter(root=domain) includes the root).
    for domain in Domain.objects.all():
        descendant_count = Domain.objects.filter(root=domain).count()
        resource_count = Resource.objects.filter(domain=domain).count()
        Domain.objects.filter(id=domain.id).update(
            descendant_count=descendant_count,
            resource_count=resource_count,
        )


class Migration(migrations.Migration):
    """Populate Domain counter caches from existing rows."""

    dependencies = [
        ("dominion", "0005_domain_descendant_count_domain_resource_count"),
    ]

    operations = [
        migrations.RunPython(populate_domain_counters, migrations.RunPython.noop),
    ]
