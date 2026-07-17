from setuptools import setup, find_packages

# Runtime dependencies for installing Dominion as a library into a host Django
# project. Kept in sync with the runtime section of requirements.in; the pinned
# requirements.txt remains the source of truth for the standalone service deploy.
INSTALL_REQUIRES = [
    "Django>=6.0",
    "djangorestframework>=3.15",
    "adrf",
    "django-oauth-toolkit>=3.0",
    "mozilla-django-oidc>=4.0",
    "django-registration>=3.4",
    "connexion>=3.2",
    "connexion[flask]",
    "swagger-ui-bundle",
    "uvicorn",
    "celery>=5.4",
    "kombu>=5.3",
    "psycopg[binary]>=3.1",
    "dj-database-url>=2.0",
    "redis>=5.0",
    "pymemcache>=4.0",
    "boto3>=1.34",
    "django-ses>=4.0",
    "gunicorn>=22.0",
    "environs>=11.0",
    "PyYAML>=6.0",
    "httpx>=0.27",
    "django-ratelimit>=4.0",
]

setup(
    name="dominion",
    version="0.1.14",
    description="Dominion — an API-driven RBAC and OIDC system for Django.",
    url="https://github.com/hedleyroos/dominion",
    license="Proprietary",
    packages=find_packages(),
    install_requires=INSTALL_REQUIRES,
    include_package_data=True,
    tests_require=[
        "tox",
    ],
    zip_safe=False,
)
