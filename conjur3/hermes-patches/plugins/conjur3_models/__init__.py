"""conjur3-models plugin — visual 3D-model picker for FreeCAD imports.

Registers two agent tools:

* ``search_3d_models`` — pure HTTP search across Printables + TraceParts
* ``pick_3d_model``    — opens a thumbnail carousel modal in the WebUI and
                         blocks until the user picks one

The picker depends on the WebUI patch at ``/app/api/model_picker.py`` and
the ``showModelPickerCard`` JS in ``/app/static/messages.js``. Without those
the ``pick_3d_model`` tool registers but raises a clear runtime error when
invoked.
"""
from __future__ import annotations

import logging

from .tools import (
    SEARCH_3D_MODELS_SCHEMA,
    PICK_3D_MODEL_SCHEMA,
    check_requirements,
    handle_search_3d_models,
    handle_pick_3d_model,
)

logger = logging.getLogger(__name__)


_TOOLS = (
    ("search_3d_models", SEARCH_3D_MODELS_SCHEMA, handle_search_3d_models, "🔎"),
    ("pick_3d_model",    PICK_3D_MODEL_SCHEMA,    handle_pick_3d_model,    "🖼️"),
)


def register(ctx) -> None:
    """Plugin entrypoint — called once at hermes-agent startup."""
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="conjur3-models",
            schema=schema,
            handler=handler,
            check_fn=check_requirements,
            emoji=emoji,
        )
    logger.info("conjur3-models: registered %d tools", len(_TOOLS))
