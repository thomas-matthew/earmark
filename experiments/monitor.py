"""Run a command while sampling its CPU and memory plus system GPU and memory use.

Usage: python monitor.py OUTPUT.csv -- COMMAND [ARGS...]
"""
import csv
import re
import subprocess
import sys
import time

INTERVAL = 2.0


def shell(*cmd: str) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def process_usage(pid: int) -> tuple[float, float]:
    """Return CPU percent (100 = one core) and resident memory in GB, children included."""
    pids, frontier = {pid}, [pid]
    while frontier:
        children = shell("pgrep", "-P", str(frontier.pop())).split()
        new = {int(c) for c in children} - pids
        pids |= new
        frontier.extend(new)
    rows = shell("ps", "-o", "%cpu=,rss=", "-p", ",".join(map(str, pids))).splitlines()
    pairs = [line.split() for line in rows if line.strip()]
    return sum(float(p[0]) for p in pairs), sum(int(p[1]) for p in pairs) / 1024 ** 2


def system_memory_gb() -> float:
    """Return memory in use, counted as active + wired + compressed pages."""
    text = shell("vm_stat")
    page = int(re.search(r"page size of (\d+)", text).group(1))
    pages = sum(
        int(re.search(rf"{label}:\s+(\d+)", text).group(1))
        for label in ("Pages active", "Pages wired down", "Pages occupied by compressor")
    )
    return pages * page / 1024 ** 3


def gpu_stats() -> tuple[float, float]:
    """Return GPU utilization percent and GPU-allocated memory in GB."""
    text = shell("ioreg", "-r", "-c", "IOAccelerator", "-d", "1", "-w", "0")
    util = re.search(r'"Device Utilization %"=(\d+)', text)
    used = re.search(r'"In use system memory"=(\d+)', text)
    return float(util.group(1)) if util else -1.0, int(used.group(1)) / 1024 ** 3 if used else -1.0


def main() -> None:
    split = sys.argv.index("--")
    out, command = sys.argv[1], sys.argv[split + 1:]
    baseline_memory = system_memory_gb()
    baseline_gpu = gpu_stats()[1]
    proc = subprocess.Popen(command)
    start, rows = time.time(), []
    while proc.poll() is None:
        cpu, rss = process_usage(proc.pid)
        util, gpu_mem = gpu_stats()
        rows.append([round(time.time() - start, 1), cpu, round(rss, 2), util, round(gpu_mem, 2), round(system_memory_gb(), 2)])
        time.sleep(INTERVAL)
    with open(out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["seconds", "process_cpu_pct", "process_rss_gb", "gpu_util_pct", "gpu_memory_gb", "system_used_gb"])
        writer.writerows(rows)
    if not rows:
        return
    column = lambda i: [r[i] for r in rows]  # noqa: E731
    busy = [r for r in rows if r[3] > 20] or rows
    print(f"\nexit {proc.returncode}, {rows[-1][0]:.0f}s, {len(rows)} samples")
    print(f"process CPU: avg {sum(column(1)) / len(rows):.0f}%, peak {max(column(1)):.0f}% (100% = one core)")
    print(f"process memory (RSS): peak {max(column(2)):.1f} GB")
    print(f"GPU utilization while busy: avg {sum(r[3] for r in busy) / len(busy):.0f}%, peak {max(column(3)):.0f}%")
    print(f"GPU memory: {baseline_gpu:.1f} GB before, peak {max(column(4)):.1f} GB")
    print(f"system memory in use: {baseline_memory:.1f} GB before, peak {max(column(5)):.1f} GB of 48 GB")


if __name__ == "__main__":
    main()
