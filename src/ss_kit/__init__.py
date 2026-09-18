"""Light runtime helpers shared by the ss services.

Importing this package writes nothing to stdout or stderr and pulls no heavy dependency; optional
integrations live behind the `web`, `mqtt`, `tooling`, and `dev` extras.
"""

from importlib.metadata import PackageNotFoundError, version

DISTRIBUTION = "ss-common"


def package_version() -> str:
    """Return the installed ss-common version, or `0+unknown` from a source checkout."""
    try:
        return version(DISTRIBUTION)
    except PackageNotFoundError:
        return "0+unknown"
