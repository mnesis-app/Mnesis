from fastapi import APIRouter, Response
import yaml
import os
import uuid
from backend.config import load_config, save_config, rotate_snapshot_token as rotate_token_logic

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

@router.post("/onboarding-complete")
async def complete_onboarding():
    """Mark onboarding as complete in config."""
    try:
        config = load_config()
        config['onboarding_completed'] = True
        save_config(config)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/config")
async def get_config(response: Response):
    """Get current configuration."""
    try:
        config = load_config()
        # Ensure default structure if missing
        if 'decay_rates' not in config:
            config['decay_rates'] = {'semantic': 0.001, 'episodic': 0.05, 'working': 0.3}
        
        # Cache for 1 hour
        response.headers["Cache-Control"] = "public, max-age=3600"
        return config
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/snapshot-token/rotate")
async def rotate_snapshot_token():
    """Rotate the snapshot read token."""
    try:
        new_token = rotate_token_logic()
        return {"token": new_token}
    except Exception as e:
         return {"status": "error", "message": str(e)}
