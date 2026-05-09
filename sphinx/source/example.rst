Example application
===================

Register your application
-------------------------

Contact dev@dominion.com to set up a new application. You will be supplied
with a *Client Id*, *Client Secret* and an *API Key*. *Client Id* and *Client Secret*
are used during the user sign up and sign in process, whereas *API Key* is used
when making API calls. An application always has exactly one *Client Id* and *Client Secret*,
and each user has his own *API Key*.

You will require a web browser and the `curl` tool.

Sign in
-------

The sign-in service implements Open ID Connect (OIDC) for authentication. The typical flow
is for your application to redirect an end user to https://signon.dominion.com to
perform registration, account activation, password retrieval and sign-in.

We will be making use of an existing site to illustrate this. This saves you from
having to build a real system for this example application.

In a browser visit `Open ID Connect Playground <https://openidconnect.net>`_ and create
an account. Click the *Edit* button on Step 1 and set the following values:

.. list-table::
   :header-rows: 0

   * - Server Template:
     - Custom

   * - Authorization Token Endpoint:
     - https://signon.dominion.com/o/authorize

   * - Token Endpoint:
     - https://signon.dominion.com/o/token/

   * - OIDC Client ID:
     - YOUR-CLIENT-ID

   * - OIDC Client Secret:
     - YOUR-CLIENT-SECRET

   * - Scope:
     - openid

Click *Save*. Click *Start*. You will be redirected to Dominion. If you do not yet have
an account then create one, and follow the prompts until you are signed in. You will eventually
be redirected back to the Open ID Connect Playground, and must complete the wizard.

The goal of the exercise is to obtain a *Decoded Token Payload* that provides all the
requested information on the authenticated user.

All popular languages and frameworks provide Open ID Connect client libraries. For example,
Django has `Mozilla Django OIDC <https://github.com/mozilla/mozilla-django-oidc>`_.
These libraries seamlessly integrate the framework's own user accounts with the OIDC user accounts.
Find one that suits your environment and use it in real applications.

Manage domains
--------------

All commands are performed in a terminal. Fetch our list of domains::

    curl -X 'GET' \
  'https://signon.dominion.com/api/v1.0/domain' \
    -H 'accept: application/json' \
    -H 'X-Auth: YOUR-API-KEY'

We don't have any domain yet::

    {
    "count": 0,
        "results": []
    }

Let's create a top-level domain::

    curl -X 'POST' \
  'https://signon.dominion.com/api/v1.0/domain' \
    -H 'accept: */*' \
    -H 'X-Auth: YOUR-API-KEY' \
    -H 'Content-Type: application/json' \
    -d '{
    "title": "Acme SA"
    }'

The response returns the newly created domain::

    {
        "id": "7363c714-0540-4ffa-a31f-e046b403b7a8",
        "parent": null,
        "title": "Acme SA"
    }

Fetch the list of domains again, and we receive::

    {
        "count": 1,
        "results": [
        {
            "id": "7363c714-0540-4ffa-a31f-e046b403b7a8",
            "parent": null,
            "title": "Acme SA"
        }
        ]
    }

Let's create a subdomain. Be sure to substitute `parent` with the `id` value as returned above::

    curl -X 'POST' \
  'https://signon.dominion.com/api/v1.0/domain' \
    -H 'accept: */*' \
    -H 'X-Auth: YOUR-API-KEY' \
    -H 'Content-Type: application/json' \
    -d '{
    "title": "Acme Western Cape",
    "parent": "ACME-SA-ID"
    }'

Domains can be created, read, updated and deleted. Refer to the API documentation for details.

User creation
-------------

Users typically register themselves via the OIDC mechanism, and, when a user authenticates against
Dominion, our application receives the user's email address, first name, last name,
and crucially the user's internal identifier. Our application can then use this `User ID` to
add users to domains, assign roles and more.

But we're getting ahead of ourselves. Sometimes we need to create the users ourselves. This is
typically required when migrating an existing application to use Dominion::

    curl -X 'POST' \
  'https://signon.dominion.com/api/v1.0/user' \
    -H 'accept: */*' \
    -H 'X-Auth: YOUR-API-KEY' \
    -H 'Content-Type: application/json' \
    -d '{
    "email": "john@example.com",
    "first_name": "John",
    "last_name": "Smith",
    "password": "secretpassword",
    "username": "johnsmith"
    }'

We receive::

    {
  "id": "68c23c3a-7455-4b75-84f3-4eb76e867d18",
  "username": "johnsmith",
  "email": "john@example.com",
  "first_name": "John",
  "last_name": "Smith",
  "api_key": "a2aee1b2-deb0-402c-a0e8-59d75804766a",
  "domains": []
    }

Unlike domains users cannot be updated or deleted. Users may belong to domains that are not under your
control, and modifying users will affect these domains.

If you plan to make API calls  as this user then make a note of the API Key now,
because you cannot retrieve it after this step. Only the user himself may retrieve his
API Key.

Roles
-----

Fetch the list of roles our application may use::

    curl -X 'GET' \
  'https://signon.dominion.com/api/v1.0/role' \
    -H 'accept: application/json' \
    -H 'X-Auth: YOUR-API-KEY'

We receive::

    {
        "count": 5,
        "results": [
            {
                "code": "access_checker",
                "domain": null,
                "title": "Access checker"
            },
            {
                "code": "anonymous",
                "domain": null,
                "title": "Anonymous"
            },
            {
                "code": "authenticated",
                "domain": null,
                "title": "Authenticated"
            },
            {
                "code": "manager",
                "domain": null,
                "title": "Manager"
            },
            {
                "code": "owner",
                "domain": null,
                "title": "Owner"
            }
        ]
    }

The default set of roles is very useful, but our application requires the custom role `General Manager`.
Let's create it on our root domain::

    curl -X 'POST' \
  'https://signon.dominion.com/api/v1.0/role' \
    -H 'accept: */*' \
    -H 'X-Auth: YOUR-API-KEY' \
    -H 'Content-Type: application/json' \
    -d '{
    "code": "general-manager",
    "domain": "7363c714-0540-4ffa-a31f-e046b403b7a8",
    "title": "General Manager"
    }'

The response returns the newly created role::

    {
        "code": "general-manager",
        "domain": "7363c714-0540-4ffa-a31f-e046b403b7a8",
        "title": "General Manager"
    }

Permissions
-----------

Fetch the list of permissions our application may use::

    curl -X 'GET' \
  'https://signon.dominion.com/api/v1.0/permission' \
    -H 'accept: application/json' \
    -H 'X-Auth: YOUR-API-KEY'

We receive::

    {
        "count": 7,
        "results": [
            {
                "code": "check_access",
                "domain": null,
                "title": "Check access"
            },
            {
                "code": "create",
                "domain": null,
                "title": "Create"
            },
            {
                "code": "delete",
                "domain": null,
                "title": "Delete"
            },
            {
                "code": "manage_roles",
                "domain": null,
                "title": "Manage roles"
            },
            {
                "code": "read",
                "domain": null,
                "title": "Read"
            },
            {
                "code": "update",
                "domain": null,
                "title": "Update"
            },
            {
                "code": "view",
                "domain": null,
                "title": "View as public"
            }
        ]
    }

The default set of permissions is very useful, but our application requires the custom permission `View Orders`.
Let's create it on our root domain::

    curl -X 'POST' \
  'https://signon.dominion.com/api/v1.0/permission' \
    -H 'accept: */*' \
    -H 'X-Auth: YOUR-API-KEY' \
    -H 'Content-Type: application/json' \
    -d '{
    "code": "view-orders",
    "domain": "7363c714-0540-4ffa-a31f-e046b403b7a8",
    "title": "View Orders"
    }'

The response returns the newly created permission::

    {
        "code": "view-orders",
        "domain": "7363c714-0540-4ffa-a31f-e046b403b7a8",
        "title": "View Orders"
    }

Role-permission mappings
------------------------

Roles and permissions are tied together per domain. Our application automatically
receives the default role-permission mapping on the root domain. Fetch the list
of role-permission mappings for our root domain::

    curl -X 'GET' \
  'https://signon.dominion.com/api/v1.0/domainrolepermission?domain=7363c714-0540-4ffa-a31f-e046b403b7a8' \
    -H 'accept: application/json' \
    -H 'X-Auth: YOUR-API-KEY'

Keep in mind that domains inherit role-permission mappings from parent domains by default. The
subdomain we created earlier is not a root domain and does not have its own role-permission mapping
at this stage, so it does not appear in the result set::

    {
    "count": 11,
    "results": [
      {
        "domain": "7363c714-0540-4ffa-a31f-e046b403b7a8",
        "id": "4e1b486a-13d7-4aa1-826f-96a6efd45d37",
        "inherit": true,
        "permission": "view",
        "role": "authenticated"
      },
      {
        "domain": "7363c714-0540-4ffa-a31f-e046b403b7a8",
        "id": "19137cd4-d9b6-407b-8759-c62b346b4048",
        "inherit": true,
        "permission": "create",
        "role": "manager"
      }
    ]
    }

Let's create a mapping that allows the `General Manager` role to `View Orders` on the root domain::

    curl -X 'POST' \
  'https://signon.dominion.com/api/v1.0/domainrolepermission' \
    -H 'accept: */*' \
    -H 'X-Auth: YOUR-API-KEY' \
    -H 'Content-Type: application/json' \
    -d '{
    "domain": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "permission": "view-orders",
    "role": "general-manager"
    }'

We receive::

    {
    "domain": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "id": "42ad49e1-39a2-45ea-aa13-b17c5cb32349",
    "inherit": true,
    "permission": "view-orders",
    "role": "general-manager"
    }

User domain roles
-----------------

We have created custom roles and permissions, and we have created a role-permission mapping.
Users may have zero or more roles per domain, so let's create some user domain roles::

    curl -X 'POST' \
  'https://signon.dominion.com/api/v1.0/userdomainrole' \
    -H 'accept: */*' \
    -H 'X-Auth: YOUR-API-KEY' \
    -H 'Content-Type: application/json' \
    -d '{
    "domain": "7363c714-0540-4ffa-a31f-e046b403b7a8",
    "role": "general-manager",
    "user": "68c23c3a-7455-4b75-84f3-4eb76e867d18"
    }'

We receive::

    {
        "domain": "7363c714-0540-4ffa-a31f-e046b403b7a8",
        "id": "b316c776-4c0e-4325-a1e8-6f96ddb5448d",
        "role": "general-manager",
        "user": "68c23c3a-7455-4b75-84f3-4eb76e867d18"
    }

A note on resources
-------------------

Resources are much like domains: a resource may live directly under a domain, or under another resource.
An example of a resource is an individual order. All the roles, permissions and mapping may also
be applied to resources for fine-grained control, but that is discussed in another section.

Access checks
-------------

All the configuration has been done. All that remains is to check whether a user has a permission on
a domain. We use John and the root domain's IDs::

    curl -X 'GET' \
  'https://signon.dominion.com/api/v1.0/access/domain/permission/68c23c3a-7455-4b75-84f3-4eb76e867d18/7363c714-0540-4ffa-a31f-e046b403b7a8/view-orders' \
    -H 'accept: application/json' \
    -H 'X-Auth: YOUR-API-KEY'

We receive::

    {
        "result": true
    }

Once roles, permissions and mappings have been set up nearly all queries performed by our example application
are access checks. Dominion does all of the heavy lifting, allowing the
example application to perform its core tasks.
