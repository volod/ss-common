"""Host memory and CPU detection, and the parallel-build budget for heavy C++/CUDA compiles.

`max_jobs()` (`ss-kit max-jobs`) is the single source of truth for `MAX_JOBS`: every job is
assumed to peak at `ram_per_job_gb`, `reserve_frac` of total memory stays free, and at most
`(cores - 2) // 2` jobs run. Memory and CPU honor cgroup limits (containers, systemd slices) and
the process CPU affinity, not only the host totals.
"""

import math
import os
from dataclasses import dataclass
from pathlib import Path

KIB_PER_GIB = 1024 * 1024
DEFAULT_RAM_PER_JOB_GB = 12.0
DEFAULT_RESERVE_FRAC = 0.20
# A fractional memory job at or above this share of one job's RAM is rounded up.
ROUND_UP_FRACTION = 0.8
# Cores kept for the rest of the system before halving the rest into build jobs.
RESERVED_CORES = 2
# Used when /proc/meminfo is unreadable (non-Linux hosts).
FALLBACK_TOTAL_KB = 8 * KIB_PER_GIB
FALLBACK_AVAILABLE_KB = 4 * KIB_PER_GIB
FALLBACK_CPU_COUNT = 4

PROC_MEMINFO = Path("/proc/meminfo")
PROC_SELF_CGROUP = Path("/proc/self/cgroup")
CGROUP_ROOT = Path("/sys/fs/cgroup")


@dataclass(frozen=True)
class MemoryInfo:
    total_kb: int
    available_kb: int


@dataclass(frozen=True)
class BuildBudget:
    jobs: int
    total_gb: float
    avail_gb: float
    usable_gb: float
    mem_jobs: int
    cpu_jobs: int

    def summary(self) -> str:
        """`jobs total_gb avail_gb usable_gb mem_jobs cpu_jobs`, one line for shell callers."""
        return (
            f"{self.jobs} {self.total_gb:.1f} {self.avail_gb:.1f} {self.usable_gb:.1f} "
            f"{self.mem_jobs} {self.cpu_jobs}"
        )


def _read_int(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return int(text)
    except ValueError:
        return None  # cgroup v2 writes "max" for no limit


def read_meminfo(path: Path = PROC_MEMINFO) -> MemoryInfo | None:
    """`MemTotal` and `MemAvailable` in KiB, or None when unreadable."""
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    values: dict[str, int] = {}
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            values[parts[0].rstrip(":")] = int(parts[1])
    if "MemTotal" not in values or "MemAvailable" not in values:
        return None
    return MemoryInfo(values["MemTotal"], values["MemAvailable"])


def own_cgroup_dir(root: Path = CGROUP_ROOT, self_cgroup: Path = PROC_SELF_CGROUP) -> Path:
    """This process's cgroup v2 directory (`0::/path` in /proc/self/cgroup), else `root`.

    Inside a container the namespace root is already the container's own group.
    """
    try:
        lines = self_cgroup.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError):
        return root
    for line in lines:
        if line.startswith("0::"):
            candidate = root / line[3:].strip().lstrip("/")
            if candidate.is_dir():
                return candidate
    return root


def cgroup_memory_kb(root: Path = CGROUP_ROOT) -> MemoryInfo | None:
    """The cgroup memory limit and headroom in KiB (v2, then v1), or None when unlimited."""
    for limit_file, usage_file in (
        (root / "memory.max", root / "memory.current"),
        (root / "memory" / "memory.limit_in_bytes", root / "memory" / "memory.usage_in_bytes"),
    ):
        limit = _read_int(limit_file)
        if limit is None:
            continue
        usage = _read_int(usage_file) or 0
        return MemoryInfo(limit // 1024, max(0, limit - usage) // 1024)
    return None


def memory_info(meminfo_path: Path = PROC_MEMINFO, cgroup_root: Path = CGROUP_ROOT) -> MemoryInfo:
    """Host memory capped by the cgroup limit; a fixed fallback when nothing is readable."""
    host = read_meminfo(meminfo_path) or MemoryInfo(FALLBACK_TOTAL_KB, FALLBACK_AVAILABLE_KB)
    group = cgroup_memory_kb(own_cgroup_dir(cgroup_root))
    if group is None or group.total_kb >= host.total_kb:
        return host
    return MemoryInfo(group.total_kb, min(host.available_kb, group.available_kb))


def cgroup_cpu_limit(root: Path = CGROUP_ROOT) -> int | None:
    """Whole CPUs allowed by the cgroup quota (v2 `cpu.max`, then v1), or None when unlimited."""
    try:
        quota_text, period_text = (root / "cpu.max").read_text(encoding="ascii").split()[:2]
        quota, period = (None if quota_text == "max" else int(quota_text)), int(period_text)
    except (OSError, ValueError, UnicodeDecodeError):
        quota = _read_int(root / "cpu" / "cpu.cfs_quota_us")
        period = _read_int(root / "cpu" / "cpu.cfs_period_us") or 0
    if quota is None or quota <= 0 or period <= 0:
        return None
    return max(1, math.ceil(quota / period))


def cpu_count(cgroup_root: Path = CGROUP_ROOT) -> int:
    """Usable CPUs: the process affinity, capped by the cgroup quota."""
    try:
        count = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        count = os.cpu_count() or FALLBACK_CPU_COUNT
    limit = cgroup_cpu_limit(own_cgroup_dir(cgroup_root))
    return min(count, limit) if limit is not None else count


def build_budget(
    total_kb: int,
    avail_kb: int,
    cpu_cores: int,
    ram_per_job_gb: float = DEFAULT_RAM_PER_JOB_GB,
    reserve_frac: float = DEFAULT_RESERVE_FRAC,
) -> BuildBudget:
    """The parallel compile budget for the given memory (KiB) and core count."""
    total_gb = total_kb / KIB_PER_GIB
    avail_gb = avail_kb / KIB_PER_GIB
    usable_gb = max(0.0, avail_gb - total_gb * reserve_frac)
    raw_mem = usable_gb / ram_per_job_gb if ram_per_job_gb > 0 else 0.0
    mem_jobs = math.ceil(raw_mem) if (raw_mem % 1) >= ROUND_UP_FRACTION else int(raw_mem)
    cpu_jobs = max(1, (cpu_cores - RESERVED_CORES) // 2)
    jobs = max(1, min(mem_jobs, cpu_jobs))
    return BuildBudget(jobs, total_gb, avail_gb, usable_gb, mem_jobs, cpu_jobs)


def host_build_budget(
    ram_per_job_gb: float = DEFAULT_RAM_PER_JOB_GB,
    reserve_frac: float = DEFAULT_RESERVE_FRAC,
) -> BuildBudget:
    memory = memory_info()
    return build_budget(
        memory.total_kb, memory.available_kb, cpu_count(), ram_per_job_gb, reserve_frac
    )


def max_jobs(
    ram_per_job_gb: float = DEFAULT_RAM_PER_JOB_GB,
    reserve_frac: float = DEFAULT_RESERVE_FRAC,
) -> int:
    """Safe `MAX_JOBS` for heavy C++/CUDA compiles on this host (at least 1)."""
    return host_build_budget(ram_per_job_gb, reserve_frac).jobs
