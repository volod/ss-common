import subprocess
import sys

import ss_contracts
import ss_kit


def test_distribution_identity() -> None:
    assert ss_kit.DISTRIBUTION == ss_contracts.DISTRIBUTION == "ss-common"
    assert ss_kit.package_version() == "0.1.0"


def test_import_is_silent_and_light() -> None:
    probe = (
        "import sys, ss_kit, ss_contracts, ss_kit.quality.footprint;"
        "heavy = {'torch', 'numpy', 'transformers', 'pydantic'} & set(sys.modules);"
        "assert not heavy, heavy"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
