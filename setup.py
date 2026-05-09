from setuptools import setup, find_packages

setup(
    name="dominion",
    version="0.1.14",
    description="",
    url="https://github.com/planktonmobi/dominion",
    license="Proprietary",
    packages=find_packages(),
    #packages=find_packages(where="app/src"),
    #packages=["dominion"],
    #package_dir={"dominion": "app/src"},
    install_requires=[
    ],
    include_package_data=True,
    tests_require=[
        "tox",
    ],
    zip_safe=False,
)
