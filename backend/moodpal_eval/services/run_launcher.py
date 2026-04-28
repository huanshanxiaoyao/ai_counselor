from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor

from .run_executor import execute_run


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='moodpal_eval_run')
_lock = threading.Lock()
_active_runs: set[str] = set()


def launch_run(run_id: str) -> Future:
    run_key = str(run_id)
    with _lock:
        if run_key in _active_runs:
            raise ValueError('run_already_launched')
        _active_runs.add(run_key)
    future = _executor.submit(_execute_with_cleanup, run_key)
    return future


def _execute_with_cleanup(run_id: str):
    try:
        execute_run(run_id)
    finally:
        with _lock:
            _active_runs.discard(str(run_id))
