from fastapi import APIRouter
from store import query_store

router = APIRouter(prefix="/api/queries", tags=["queries"])

@router.get("")
async def list_queries():
    return query_store.get_queries()

@router.post("/{query_id}/favorite")
async def toggle_favorite(query_id: str):
    return query_store.toggle_favorite(query_id)
