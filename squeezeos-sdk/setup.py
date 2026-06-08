from setuptools import setup, find_packages

setup(
    name="squeezeos",
    version="1.0.0",
    description="Official Python SDK for SqueezeOS - Institutional Options & Equity Analysis",
    author="ScriptMasterLabs",
    packages=find_packages(),
    install_requires=[
        "requests>=2.25.1",
        "xrpl-py>=2.3.0"
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.8',
)
