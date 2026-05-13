from fastapi import APIRouter
from sqlmodel import select

from app.api.deps import SessionDep
from app.models import RequestLog, TaskLog

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/requests", response_model=list[RequestLog])
def list_request_logs(
    session: SessionDep,
    platform: str | None = None,
    shop_id: str | None = None,
    task_id: int | None = None,
    limit: int = 100,
) -> list[RequestLog]:
    statement = select(RequestLog).order_by(RequestLog.created_at.desc()).limit(limit)
    if platform:
        statement = statement.where(RequestLog.platform == platform)
    if shop_id:
        statement = statement.where(RequestLog.shop_id == shop_id)
    if task_id:
        statement = statement.where(RequestLog.task_id == task_id)
    return list(session.exec(statement).all())


@router.get("/tasks", response_model=list[TaskLog])
def list_task_logs(
    session: SessionDep,
    platform: str | None = None,
    shop_id: str | None = None,
    limit: int = 100,
) -> list[TaskLog]:
    statement = select(TaskLog).order_by(TaskLog.created_at.desc()).limit(limit)
    if platform:
        statement = statement.where(TaskLog.platform == platform)
    if shop_id:
        statement = statement.where(TaskLog.shop_id == shop_id)
    return list(session.exec(statement).all())
