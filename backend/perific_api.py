"""API endpoint(s) for core.perific — the Perific One power reading.

Deliberately its own small file rather than more lines in the big api.py:
Fas 2's whole job is "one new data source, visible in the UI", so its API
surface should be easy to find as one self-contained piece, the same way
core/perific/ is one self-contained package. Zaptec, Nibe and the governor
will each get an equivalent *_api.py of their own in later phases.
"""

from fastapi import APIRouter, HTTPException
from loguru import logger

router = APIRouter()


@router.get("/api/perific/power")
async def get_perific_power():
    """Return the current total site power draw, per Perific One.

    Response shape mirrors the rest of the API (camelCase, a plain dict):
        {"powerKw": 6.93, "available": true}
        {"powerKw": null, "available": false}   # sensor unavailable right now

    ``available: false`` is not an error — it's the normal state whenever
    Perific's own cloud poll hasn't refreshed, or (as seen live on 2026-08-29)
    whenever nothing has been read yet. The frontend should show "no data"
    for this case, not an error banner.
    """
    # Imported inside the function, not at module load time: app.py builds
    # the real bess_controller (and now perific_reader) as a module-level
    # side effect, which backend/tests/conftest.py stubs out with a
    # MagicMock so importing this router in tests doesn't require a live
    # Home Assistant connection. Same reason api.py imports bess_controller
    # this way for every other endpoint.
    from app import bess_controller

    try:
        power_kw = bess_controller.perific_reader.get_power_total_kw()
    except Exception as e:
        logger.error(f"Error reading Perific power: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"powerKw": power_kw, "available": power_kw is not None}
