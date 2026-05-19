from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="proof402",
    version="1.1.0",
    description="x402/HTTP 402 payment middleware for FastAPI and Flask. Gate any API behind RLUSD micropayments on XRP Ledger via 402Proof. Sub-millisecond local HMAC verification. Zero API keys.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Script Master Labs",
    url="https://four02proof.onrender.com",
    project_urls={
        "Homepage": "https://four02proof.onrender.com",
        "Repository": "https://github.com/timwal78/squeezeos",
        "Bug Tracker": "https://github.com/timwal78/squeezeos/issues",
    },
    packages=find_packages(),
    python_requires=">=3.9",
    keywords=[
        "x402", "xrpl", "rlusd", "payment", "ai-agents",
        "fastapi", "flask", "wsgi", "middleware", "http-402",
        "micropayment", "agent-economy", "402proof"
    ],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Middleware",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    license="MIT",
)
