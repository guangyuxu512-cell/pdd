from fastapi import APIRouter

from app.api.deps import SessionDep
from app.models import AIAnalyzeGoodsRequest, AIExplainErrorRequest, AISuggestCleanupRequest
from app.services.ai_service import AIService

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/goods/analyze")
def analyze_goods(data: AIAnalyzeGoodsRequest, session: SessionDep) -> dict:
    return AIService(session).analyze_goods_payload(data.payload)


@router.post("/errors/explain")
def explain_error(data: AIExplainErrorRequest, session: SessionDep) -> dict:
    return AIService(session).explain_error(data.request_log, data.response_log)


@router.post("/goods/cleanup-suggest")
def suggest_cleanup(data: AISuggestCleanupRequest, session: SessionDep) -> dict:
    return AIService(session).suggest_cleanup(data.goods_stats)
