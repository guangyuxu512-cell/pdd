from datetime import datetime

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.deps import SessionDep
from app.models import AppConfig, AppConfigRead, AppConfigWrite

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=list[AppConfigRead])
def list_config(session: SessionDep) -> list[AppConfigRead]:
    rows = session.exec(select(AppConfig).order_by(AppConfig.key)).all()
    result: list[AppConfigRead] = []
    for row in rows:
        value = "***" if row.sensitive else row.value
        result.append(
            AppConfigRead(
                key=row.key,
                value=value,
                value_type=row.value_type,
                sensitive=row.sensitive,
                description=row.description,
            )
        )
    return result


@router.put("/{key}", response_model=AppConfigRead)
def set_config(key: str, data: AppConfigWrite, session: SessionDep) -> AppConfigRead:
    row = session.exec(select(AppConfig).where(AppConfig.key == key)).first()
    if row:
        row.value = data.value
        row.value_type = data.value_type
        row.sensitive = data.sensitive
        row.description = data.description
        row.updated_at = datetime.now()
    else:
        row = AppConfig(key=key, **data.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return AppConfigRead(
        key=row.key,
        value="***" if row.sensitive else row.value,
        value_type=row.value_type,
        sensitive=row.sensitive,
        description=row.description,
    )


@router.get("/{key}", response_model=AppConfigRead)
def get_config(key: str, session: SessionDep) -> AppConfigRead:
    row = session.exec(select(AppConfig).where(AppConfig.key == key)).first()
    if not row:
        raise HTTPException(status_code=404, detail="config not found")
    return AppConfigRead(
        key=row.key,
        value="***" if row.sensitive else row.value,
        value_type=row.value_type,
        sensitive=row.sensitive,
        description=row.description,
    )
