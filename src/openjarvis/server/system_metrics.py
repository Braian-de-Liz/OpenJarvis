"""Live host telemetry for the ``/jarvis`` HUD.

``GET /api/system/metrics`` returns CPU / RAM / network from ``psutil`` and
GPU utilisation / temperature from NVML (first device). GPU fields are
``None`` when no NVIDIA GPU is visible. Without ``psutil`` the route answers
503 so the HUD keeps its DEMO fallback.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def _load_psutil() -> Optional[Any]:
    try:
        import psutil
    except ImportError:
        return None
    return psutil


def _default_gpu_reader() -> Callable[[], Optional[Dict[str, float]]]:
    """Return a reader for the first GPU, or one that always yields ``None``."""
    try:
        from openjarvis.telemetry.gpu_monitor import GpuMonitor

        monitor = GpuMonitor()
    except Exception:
        logger.debug("GPU monitor unavailable", exc_info=True)
        return lambda: None

    def read() -> Optional[Dict[str, float]]:
        snaps = monitor.snapshot()
        if not snaps:
            return None
        return {"gpu": snaps[0].utilization_pct, "temp": snaps[0].temperature_c}

    return read


def create_system_metrics_router(
    psutil_module: Optional[Any] = None,
    gpu_reader: Optional[Callable[[], Optional[Dict[str, float]]]] = None,
) -> APIRouter:
    """Build the ``/api/system/metrics`` router (dependencies injectable for tests)."""
    ps = psutil_module if psutil_module is not None else _load_psutil()
    read_gpu = gpu_reader if gpu_reader is not None else _default_gpu_reader()
    router = APIRouter(tags=["system"])

    # Network throughput is a delta between calls; cpu_percent(None) also
    # measures since the previous call, so prime both now.
    last: Dict[str, Any] = {"net": None, "t": time.monotonic()}
    if ps is not None:
        ps.cpu_percent(interval=None)
        last["net"] = ps.net_io_counters()

    @router.get("/api/system/metrics")
    async def system_metrics() -> Any:
        if ps is None:
            return JSONResponse({"detail": "psutil not installed"}, status_code=503)

        now = time.monotonic()
        net = ps.net_io_counters()
        prev, elapsed = last["net"], max(now - last["t"], 1e-6)
        up = down = 0.0
        if prev is not None:
            # Counters can reset (adapter change); never report negatives.
            up = max(net.bytes_sent - prev.bytes_sent, 0) * 8 / 1e6 / elapsed
            down = max(net.bytes_recv - prev.bytes_recv, 0) * 8 / 1e6 / elapsed
        last["net"], last["t"] = net, now

        gpu: Optional[Dict[str, float]] = None
        try:
            gpu = read_gpu()
        except Exception:
            logger.debug("GPU read failed", exc_info=True)

        return {
            "cpu": float(ps.cpu_percent(interval=None)),
            "ram": float(ps.virtual_memory().percent),
            "gpu": gpu["gpu"] if gpu else None,
            "temp": gpu["temp"] if gpu else None,
            "netUp": round(up, 3),
            "netDown": round(down, 3),
        }

    return router
