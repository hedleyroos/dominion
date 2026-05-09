from setuptools import setup, find_packages

setup(
    name="dominion",
    version="0.1.14",
    description="",
    url="https://github.com/hedleyroos/dominion",
    license="Proprietary",
    packages=find_packages(),
    install_requires=[
    ],
    include_package_data=True,
    tests_require=[
        "tox",
    ],
    zip_safe=False,
)
