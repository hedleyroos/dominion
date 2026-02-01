import abc
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Process, Queue, Pool
from random import choice
from time import time

import requests
from django import db
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.wsgi import get_wsgi_application


URL = "http://localhost:8090/api/v1.0/"
LOG = False

# Adjust path
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/app/src')

# Configure Django so the ORM works
if not settings.configured:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
    application = get_wsgi_application()


# We can import models after Django is configured
from triplea.models import Domain, Resource, Role, UserDomainRole, UserResourceRole

# We need these throughout
User = get_user_model()
role_manager = Role.objects.get(code="manager")


# API calls
def post(*args, **kwargs):
    path = args[0][0]
    payload = args[0][1]
    user_id = args[0][2]
    response = requests.post(
        URL + path, json=payload, headers={"X-Auth": str(user_id)}
    )
    message = (
        "USER ID: %s\n"
        "PAYLOAD: %s\n"
        "RESPONSE: %s\n"
        "--------\n"
    ) % (user_id, payload, response.json())
    global LOG
    if LOG:
        print(message)


def get(*args, **kwargs):
    path = args[0][0]
    id = args[0][1]
    user_id = args[0][2]
    response = requests.get(
        URL + path + "/" + id, headers={"X-Auth": str(user_id)}
    )
    global LOG
    if LOG:
        print(response.json())


################
# Lazily load the resource user mapping
################

def load_batch(start, end):
    # Raw SQL so we can use rowid for efficient offset equivalent queries
    di = {}
    for record in UserResourceRole.objects.raw("select distinct on(resource_id) resource_id, id, user_id from triplea_userresourcerole where rowid>=%s and rowid<=%s" % (start, end)):
        di[record.resource_id] = record.user_id
    return di


class ResourceUserMapping(metaclass=abc.ABCMeta):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.di = {}
        self.max = 0

    def __setitem__(self, key, value):
        self.di[key] = value

    def __getitem__(self, key):
        while key not in self.di:
            if len(self.di.keys()) >= self.max:
                raise KeyError(key)
            self.load_more()
        return self.di[key]

    def refresh(self):
        self.max = UserResourceRole.objects.all().distinct("resource_id").count()

    def load_more(self):
        db.connections.close_all()

        with Pool(8) as pool:
            results = []
            start = len(self.di.keys())
            for i in range(1, 9):
                end = start + 250000
                results.append(pool.apply_async(load_batch, (start, end)))
                start = end
                if end >= self.max:
                    break
            for result in results:
                for k, v in result.get().items():
                    self.di[k] = v


resource_user_mapping = ResourceUserMapping()

################



################
# Create users
################

#NUM = 10000
NUM = 1000

# Create through ORM, not API.
if not User.objects.all().exists():
    for i in range(NUM):
        user, created = User.objects.get_or_create(username="user%.8d" % i, email="user%.8d@aaa.com" % i)
        if created:
            # Set api key to id to make testing easier
            user.api_key = user.id
            user.set_password("local")
            user.save()

################



# We need these for speedy lookups later
user_ids = [o for o in User.objects.all().order_by("username").values_list("id", flat=True)]



################
# Create domains
################

NUM = 100


def create_domains(num):
    l = len(user_ids)
    for i in range(num):
        yield "domain", {"title": "Domain %.8d" % i}, user_ids[i % l]


created_domains = False
if not Domain.objects.all().exists():
    #NUM = 10
    start = time()
    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(post, create_domains(NUM))
    print("Created %s domains in %s seconds" % (NUM, time() - start))
    created_domains = True

################



################
# Read domains
################

NUM = 100


def read_domains(num):
    l = len(user_ids)
    for n, domain in enumerate(Domain.objects.all().order_by("title")[:num]):
        yield "domain", str(domain.id), user_ids[n % l]


start = time()
with ThreadPoolExecutor(max_workers=20) as executor:
    executor.map(get, read_domains(NUM))
print("Read %s domains in %s seconds" % (NUM, time() - start))

################



# We need these for speedy lookups later
domain_ids = [o for o in Domain.objects.all().order_by("title").values_list("id", flat=True)]
top_level_domains = Domain.objects.filter(parent__isnull=True).order_by("title")



################
# Create user domain roles
################

NUM = 100


def create_userdomainroles(num):
    # Every top level domain gets an extra NUM user domain roles
    l = len(user_ids)
    for i, domain in enumerate(top_level_domains):
        for j in range(num):
            yield "userdomainrole", {"user": str(user_ids[(i*NUM+j) % l]), "domain": str(domain_ids[i % l]), "role": role_manager.code}, user_ids[i % l]


if created_domains:
    start = time()
    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(post, create_userdomainroles(NUM))
    print("Created %s user domain roles in %s seconds" % (NUM*len(top_level_domains), time() - start))

################



################
# Create resources with no parents
################

#NUM = 500000
NUM = 10000

# We need this structure for create_resources_with_no_parents
domains = []
for domain in Domain.objects.all().order_by("title"):
    domain.user_id = UserDomainRole.objects.filter(domain=domain).first().user.id
    domains.append(domain)


def create_resources_with_no_parents(num):
    ld = len(domain_ids)
    lu = len(user_ids)
    for i in range(num):
        domain = domains[i % ld]
        yield "resource", {"domain": str(domain.id), "urn": "urn%.8d" % i}, str(domain.user_id)


if not Resource.objects.filter(parent__isnull=True).exists():
    start = time()
    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(post, create_resources_with_no_parents(NUM))
    print("Created %s resources with no parents in %s seconds" % (NUM, time() - start))

################



################
# Create resources with random parents
################

#NUM = 500000
NUM = 10000

# We need this structure for create_resources_with_random_parents
if not Resource.objects.filter(parent__isnull=False).exists():
    resource_user_mapping.refresh()
    resources = []
    for resource in Resource.objects.filter(parent__isnull=True).order_by("urn")[:NUM]:
        resource.user_id = resource_user_mapping[resource.id]
        resources.append(resource)


def create_resources_with_random_parents(num):
    for i in range(num):
        parent = choice(resources)
        yield "resource", {"domain": str(parent.domain.id), "urn": "urnr%.8d" % i, "parent": str(parent.id)}, parent.user_id


if not Resource.objects.filter(parent__isnull=False).exists():
    start = time()
    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(post, create_resources_with_random_parents(NUM))
    print("Created %s resources with random parents in %s seconds" % (NUM, time() - start))

    del resources


################



################
# Read resources with no parents
################

NUM = 10000

# We need this structure for read_resources_with_no_parents
resource_user_mapping.refresh()
resources = []
for resource in Resource.objects.filter(parent__isnull=True).order_by("urn")[:NUM]:
    resource.user_id = resource_user_mapping[resource.id]
    resources.append(resource)


def read_resources_with_no_parents(num):
    for resource in resources[:num]:
        yield "resource", str(resource.id), str(resource.user_id)


start = time()
with ThreadPoolExecutor(max_workers=20) as executor:
    executor.map(get, read_resources_with_no_parents(NUM))
print("Read %s resources with no parent in %s seconds" % (NUM, time() - start))

del resources

################



################
# Read resources with random parents
################

NUM = 10000

# We need this structure for read_resources_with_random_parents
resource_user_mapping.refresh()
resources = []
for resource in Resource.objects.filter(parent__isnull=False).order_by("urn")[:NUM]:
    resource.user_id = resource_user_mapping[resource.parent_id]
    resources.append(resource)


def read_resources_with_random_parents(num):
    for resource in resources[:num]:
        yield "resource", str(resource.id), str(resource.user_id)


start = time()
with ThreadPoolExecutor(max_workers=20) as executor:
    executor.map(get, read_resources_with_random_parents(NUM))
print("Read %s resources with random parents in %s seconds" % (NUM, time() - start))

del resources

################


################
# Read random resources as other users
################

NUM = 10000


def read_random_resources_as_random_other_users(num):
    l = len(user_ids)
    for n, resource in enumerate(Resource.objects.all()[:num]):
        yield "resource", str(resource.id), choice(user_ids)


start = time()
with ThreadPoolExecutor(max_workers=20) as executor:
    executor.map(get, read_random_resources_as_random_other_users(NUM))
print("Read %s random resources as random other users in %s seconds" % (NUM, time() - start))

################

