"""
app/api/routes/config_routes.py
--------------------------------
Endpoints for reading and updating the application configuration.

config.yaml is the persistent store. Changes take effect for the next
camera start — running cameras use the config snapshot captured when they
were started and must be restarted to pick up new settings.

GET   /api/config/    Return the complete current config (with defaults filled)
PATCH /api/config/    Merge the supplied fields into config.yaml and save

Only fields included in the request body are updated (exclude_none=True).
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional, Union

from app.config import get_config, save_config
from app.schemas.config_schemas import ConfigUpdate
router = APIRouter()



@router.get("/")
def get_full_config():
    """Return the full config with all defaults applied."""
    return get_config()


@router.patch("/")
def update_config(body: ConfigUpdate):
    """
    Merge partial config into config.yaml.
    Only fields present in the request body are written; others are untouched.
    Returns the updated full config.
    """
    cfg = get_config()
    # exclude_none ensures fields not provided in the request are not overwritten
    data = body.model_dump(exclude_none=True)
    cfg.update(data)
    save_config(cfg)
    return {"message": "Config updated", "config": cfg}
