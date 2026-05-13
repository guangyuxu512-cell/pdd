from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.deps import SessionDep
from app.models import CaptchaChallenge, CaptchaChallengeCreate, CaptchaChallengeRead, CaptchaChallengeSubmit
from app.services.captcha_service import CaptchaService

router = APIRouter(prefix="/captcha", tags=["captcha"])


@router.post("/challenges", response_model=CaptchaChallengeRead)
def create_challenge(data: CaptchaChallengeCreate, session: SessionDep) -> CaptchaChallenge:
    return CaptchaService(session).create_challenge(data)


@router.get("/challenges", response_model=list[CaptchaChallengeRead])
def list_challenges(session: SessionDep, status: str | None = None) -> list[CaptchaChallenge]:
    statement = select(CaptchaChallenge).order_by(CaptchaChallenge.created_at.desc())
    if status:
        statement = statement.where(CaptchaChallenge.status == status)
    return list(session.exec(statement).all())


@router.get("/challenges/{challenge_id}", response_model=CaptchaChallengeRead)
def get_challenge(challenge_id: int, session: SessionDep) -> CaptchaChallenge:
    challenge = session.get(CaptchaChallenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="captcha challenge not found")
    return challenge


@router.post("/challenges/{challenge_id}/submit", response_model=CaptchaChallengeRead)
def submit_challenge(
    challenge_id: int,
    data: CaptchaChallengeSubmit,
    session: SessionDep,
) -> CaptchaChallenge:
    return CaptchaService(session).submit_challenge(challenge_id, data)


@router.post("/challenges/{challenge_id}/cancel", response_model=CaptchaChallengeRead)
def cancel_challenge(challenge_id: int, session: SessionDep) -> CaptchaChallenge:
    return CaptchaService(session).cancel_challenge(challenge_id)


@router.post("/providers/test")
def test_provider() -> dict[str, str]:
    return {"provider": "manual", "status": "ok"}
