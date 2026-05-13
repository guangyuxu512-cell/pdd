from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.deps import SessionDep
from app.core.task_runner import task_runner
from app.models import Task, TaskCreate, TaskLog, TaskRead, TaskStatus, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskRead])
def list_tasks(
    session: SessionDep,
    status: str | None = None,
    platform: str | None = None,
    shop_id: str | None = None,
) -> list[Task]:
    statement = select(Task).order_by(Task.created_at.desc())
    if status:
        statement = statement.where(Task.status == status)
    if platform:
        statement = statement.where(Task.platform == platform)
    if shop_id:
        statement = statement.where(Task.shop_id == shop_id)
    return list(session.exec(statement).all())


@router.post("", response_model=TaskRead)
def create_task(data: TaskCreate, session: SessionDep) -> Task:
    task = Task.model_validate(data)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: int, session: SessionDep) -> Task:
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(task_id: int, data: TaskUpdate, session: SessionDep) -> Task:
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task.status == TaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail="running task cannot be edited")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(task, key, value)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.post("/dispatch")
def dispatch_tasks(limit: int | None = None) -> dict[str, list[int]]:
    return {"dispatched_task_ids": task_runner.dispatch_pending(limit)}


@router.post("/{task_id}/cancel", response_model=TaskRead)
def cancel_task(task_id: int, session: SessionDep) -> Task:
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task.status == TaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail="running task cannot be cancelled in v1")
    task.status = TaskStatus.CANCELLED
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.get("/{task_id}/logs", response_model=list[TaskLog])
def list_task_logs(task_id: int, session: SessionDep) -> list[TaskLog]:
    return list(
        session.exec(
            select(TaskLog).where(TaskLog.task_id == task_id).order_by(TaskLog.created_at.desc())
        ).all()
    )
