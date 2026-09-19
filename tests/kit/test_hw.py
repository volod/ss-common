import json
import subprocess
import sys
from pathlib import Path

import pytest

from ss_kit import hw
from ss_kit.cli import main

GIB_KB = hw.KIB_PER_GIB


@pytest.mark.parametrize(
    ("total_gb", "avail_gb", "cores", "expected"),
    [
        (64, 60, 32, 4),  # usable 47.2 GiB -> 3.93 jobs rounds up to 4
        (64, 50, 32, 3),  # usable 37.2 GiB -> 3.1 jobs
        (16, 10, 32, 1),  # memory-bound, never below one job
        (512, 500, 8, 3),  # CPU-bound: (8 - 2) // 2
        (8, 1, 2, 1),  # no usable memory and two cores still build with one job
    ],
)
def test_build_budget(total_gb: int, avail_gb: int, cores: int, expected: int) -> None:
    budget = hw.build_budget(total_gb * GIB_KB, avail_gb * GIB_KB, cores)
    assert budget.jobs == expected
    assert budget.jobs == max(1, min(budget.mem_jobs, budget.cpu_jobs))


def test_budget_summary_matches_the_shell_format() -> None:
    budget = hw.build_budget(64 * GIB_KB, 50 * GIB_KB, 32, ram_per_job_gb=12, reserve_frac=0.2)
    assert budget.summary() == "3 64.0 50.0 37.2 3 15"
    assert hw.build_budget(GIB_KB, GIB_KB, 4, ram_per_job_gb=0).mem_jobs == 0


def test_read_meminfo(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:  1000 kB\nMemFree: 10 kB\nMemAvailable: 600 kB\n")
    assert hw.read_meminfo(meminfo) == hw.MemoryInfo(1000, 600)
    meminfo.write_text("MemTotal: 1000 kB\n")
    assert hw.read_meminfo(meminfo) is None
    assert hw.read_meminfo(tmp_path / "absent") is None


def _cgroup(tmp_path: Path, **files: str) -> Path:
    root = tmp_path / "cgroup"
    for name, text in files.items():
        path = root / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    root.mkdir(exist_ok=True)
    return root


def test_memory_info_honors_cgroup_limits(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(f"MemTotal: {64 * GIB_KB} kB\nMemAvailable: {60 * GIB_KB} kB\n")
    limited = _cgroup(tmp_path, **{"memory.max": str(16 * 2**30), "memory.current": str(4 * 2**30)})
    assert hw.memory_info(meminfo, limited) == hw.MemoryInfo(16 * GIB_KB, 12 * GIB_KB)

    unlimited = _cgroup(tmp_path / "u", **{"memory.max": "max"})
    assert hw.memory_info(meminfo, unlimited).total_kb == 64 * GIB_KB

    v1 = _cgroup(tmp_path / "v1", **{"memory/memory.limit_in_bytes": str(2**62)})
    assert hw.memory_info(meminfo, v1).total_kb == 64 * GIB_KB  # "unlimited" v1 value
    assert hw.memory_info(tmp_path / "none", tmp_path / "none") == hw.MemoryInfo(
        hw.FALLBACK_TOTAL_KB, hw.FALLBACK_AVAILABLE_KB
    )


def test_cpu_limits(tmp_path: Path) -> None:
    assert hw.cgroup_cpu_limit(_cgroup(tmp_path / "a", **{"cpu.max": "250000 100000"})) == 3
    assert hw.cgroup_cpu_limit(_cgroup(tmp_path / "b", **{"cpu.max": "max 100000"})) is None
    v1 = _cgroup(
        tmp_path / "c",
        **{"cpu/cpu.cfs_quota_us": "50000", "cpu/cpu.cfs_period_us": "100000"},
    )
    assert hw.cgroup_cpu_limit(v1) == 1
    assert hw.cgroup_cpu_limit(_cgroup(tmp_path / "d", cpu__cpu__cfs_quota_us="-1")) is None
    assert hw.cpu_count(_cgroup(tmp_path / "e", **{"cpu.max": "100000 100000"})) == 1
    assert hw.cpu_count(tmp_path / "none") >= 1


def test_own_cgroup_dir(tmp_path: Path) -> None:
    root = _cgroup(tmp_path, **{"user.slice__app.scope__memory.max": "max"})
    self_cgroup = tmp_path / "self"
    self_cgroup.write_text("0::/user.slice/app.scope\n")
    assert hw.own_cgroup_dir(root, self_cgroup) == root / "user.slice/app.scope"
    self_cgroup.write_text("0::/gone\n")
    assert hw.own_cgroup_dir(root, self_cgroup) == root
    assert hw.own_cgroup_dir(root, tmp_path / "absent") == root


def test_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["max-jobs"]) == 0
    assert int(capsys.readouterr().out) >= 1
    args = ["--total-kb", str(64 * GIB_KB), "--avail-kb", str(50 * GIB_KB), "--cpu-cores", "32"]
    assert main(["build-budget", *args]) == 0
    assert capsys.readouterr().out == "3 64.0 50.0 37.2 3 15\n"
    assert main(["hw"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["cpu_count"] >= 1 and report["memory"]["total_kb"] > 0


def test_module_entrypoint_prints_one_number() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ss_kit", "max-jobs"], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip().isdigit() and result.stderr == ""
