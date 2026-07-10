"""API v1. Breaking wire changes mean a v2 package, not edits here."""

from fastapi import APIRouter

from engram_api.routers.v1 import events, memories, proposals, search

router = APIRouter()
router.include_router(memories.router)
router.include_router(proposals.router)
router.include_router(search.router)
router.include_router(events.router)
