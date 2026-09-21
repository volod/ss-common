import subprocess
import sys

import ss_contracts
import ss_kit


def test_distribution_identity() -> None:
    assert ss_kit.DISTRIBUTION == ss_contracts.DISTRIBUTION == "ss-common"
    assert ss_kit.package_version() == "0.2.1"


def test_import_is_silent_and_light() -> None:
    probe = (
        "import sys, ss_kit, ss_contracts, ss_kit.quality.footprint;"
        "import ss_kit.env, ss_kit.settings, ss_kit.paths, ss_kit.logging, ss_kit.security;"
        "import ss_kit.hw, ss_kit.sidecar, ss_kit.mqtt, ss_contracts.topics;"
        "heavy = {'torch', 'numpy', 'transformers', 'pydantic'} & set(sys.modules);"
        "assert not heavy, heavy"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
