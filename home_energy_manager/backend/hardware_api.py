"""API endpoint for core.hardware_info — the "Info om hårdvara" page.

Deliberately its own small file rather than more lines in the big api.py,
same reasoning as perific_api.py/nibe_api.py/governor_api.py: this page's
whole job is "one new, self-contained read", so its API surface should be
easy to find as one piece on its own. Unlike those three, there's no
writing and no settings-store state here at all — this is a single GET
that assembles one snapshot across every product core.hardware_info
knows about and hands it straight back.
"""

from fastapi import APIRouter

from core.hardware_info import fetch_hardware_info

router = APIRouter()


@router.get("/api/hardware/info")
async def get_hardware_info() -> dict:
    """Return identification facts (serial numbers, firmware/model
    versions, VIN, MAC) for every physical product in this installation —
    see core/hardware_info.py's own docstring for the full field list and
    why individual fields are null rather than fabricated when their
    entity is unavailable.
    """
    # Imported inside the function, not at module load time: app.py builds
    # the real bess_controller as a module-level side effect, which tests
    # importing this router can stub out with a MagicMock without a live
    # Home Assistant connection. Same reason perific_api.py/nibe_api.py
    # import bess_controller this way for every other endpoint.
    from app import bess_controller

    controller = bess_controller.nibe_controller
    return fetch_hardware_info(controller.base_url, controller.headers)
