# The device's free memory, and how many translation workers it can afford.
#
# The shader translation stage cuts the shaders into batches and runs one translation process per batch: as many as the device has cores.
# Each of those processes holds the .NET runtime and its own batch, so a phone with little memory free runs out of it and the system
# kills the build (the player sees the port interrupted, with nothing to read). The number of processes therefore follows the memory
# the device has free when the stage starts: plenty of it -> one per core (as before), little of it -> fewer, so the build finishes.
#
# The rules live here, apart from the pipeline, so they can be tested without a device: reading the memory is one function, deciding
# the number is another.
import os


def _mb(name, default):
    """A budget in MB from the environment (a number of MB), or the default when it is unset or not a number"""
    try:
        return int(os.environ.get(name, '') or default)
    except ValueError:
        return default


WORKER_MB = _mb('NX2A_MEM_WORKER_MB', 600)    # MB one translation process needs: its runtime and its batch's work
RESERVE_MB = _mb('NX2A_MEM_RESERVE_MB', 800)  # MB kept free for the app, the porter and the system
FLOOR_MB = _mb('NX2A_MEM_FLOOR_MB', 1024)     # MB below which the translation has no room to run at all
MIN_JOBS = 1        # the fewest processes the stage runs with
FORCED_JOBS = 2    # the low-memory mode's ceiling (--low-mem)


def available_mb(path='/proc/meminfo'):
    """The device's free memory in MB (Linux: /proc/meminfo's MemAvailable; None where there is no /proc: a Mac, a Windows)"""
    try:
        with open(path) as f:
            for ln in f:
                if ln.startswith('MemAvailable:'):
                    return int(ln.split()[1]) / 1024
    except OSError:
        pass
    return None


def jobs(avail_mb, cpus, forced=False, worker_mb=None, reserve_mb=None, floor_mb=None):
    """The translation workers to run: as many as the free memory affords, at most one per core.
    avail_mb None (no /proc: a desktop machine) -> one per core, as before.
    0 when the free memory does not even afford one: the caller stops with a clear error instead of being killed.
    forced: the low-memory mode's ceiling."""
    worker_mb = WORKER_MB if worker_mb is None else worker_mb
    reserve_mb = RESERVE_MB if reserve_mb is None else reserve_mb
    floor_mb = FLOOR_MB if floor_mb is None else floor_mb
    if avail_mb is None:
        n = cpus
    elif avail_mb < floor_mb:
        return 0
    else:
        n = max(MIN_JOBS, int((avail_mb - reserve_mb) // worker_mb))
    n = min(n, cpus)
    return min(n, FORCED_JOBS) if forced else n


def basis(avail_mb, forced):
    """What the number of workers was decided on, for the log: the player reads why the build is slow"""
    if forced: return 'forced low (--low-mem)'
    if avail_mb is None: return 'one per core (the device reports no memory)'
    return 'what the free memory affords'
