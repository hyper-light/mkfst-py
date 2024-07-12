import os

from setuptools import find_packages, setup

current_directory = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(current_directory, "README.md"), "r") as readme:
    package_description = readme.read()

version_string = ""
with open(os.path.join(current_directory, ".version"), "r") as version_file:
    version_string = version_file.read()

setup(
    name="mkfst",
    version=version_string,
    description="MKFST (Make Fast) is a high-performance, async, non-ASGI, Python HTTP webserver framework.",
    long_description=package_description,
    long_description_content_type="text/markdown",
    author="Ada Lundhe",
    author_email="ada@hyperlight.dev",
    url="https://github.com/hyper-light/mkfst-py",
    packages=find_packages(),
    keywords=[
        "pypi",
        "cicd",
        "python",
        "performance",
    ],
    classifiers=[
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        "psutil",
        "uvloop",
        "pydantic",
        "zstandard",
        "cryptography",
        "python-dotenv",
        "orjson",
        "msgspec",
    ],
    python_requires=">=3.11",
)
