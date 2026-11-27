import os
import platform
import shutil
import time

import config

STARTED = time.time()


def uptime() -> str:
    s = int(time.time() - STARTED)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{d}d {h}h {m}m {s}s" if d else f"{h}h {m}m {s}s"


def snapshot() -> dict:
    info = {"python": platform.python_version(), "os": platform.system(), "uptime": uptime()}
    try:
        import psutil

        vm = psutil.virtual_memory()
        info.update(
            cpu=psutil.cpu_percent(interval=0.2),
            ram=f"{vm.used / 2**30:.1f}/{vm.total / 2**30:.1f} GB ({vm.percent:.0f}%)",
        )
    except Exception:
        info.update(cpu=None, ram="n/a")
    try:
        du = shutil.disk_usage(config.DATA_DIR if os.path.isdir(config.DATA_DIR) else ".")
        info["disk"] = f"{du.used / 2**30:.1f}/{du.total / 2**30:.1f} GB"
    except Exception:
        info["disk"] = "n/a"
    return info
