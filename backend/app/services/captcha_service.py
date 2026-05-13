from datetime import datetime

from fastapi import HTTPException
from sqlmodel import Session

from app.models import CaptchaChallenge, CaptchaChallengeCreate, CaptchaChallengeSubmit, CaptchaStatus


class CaptchaService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_challenge(self, data: CaptchaChallengeCreate) -> CaptchaChallenge:
        challenge = CaptchaChallenge.model_validate(data)
        challenge.status = CaptchaStatus.WAITING
        self.session.add(challenge)
        self.session.commit()
        self.session.refresh(challenge)
        return challenge

    def submit_challenge(self, challenge_id: int, data: CaptchaChallengeSubmit) -> CaptchaChallenge:
        challenge = self.session.get(CaptchaChallenge, challenge_id)
        if not challenge:
            raise HTTPException(status_code=404, detail="captcha challenge not found")
        if challenge.status in {CaptchaStatus.CANCELLED, CaptchaStatus.EXPIRED}:
            raise HTTPException(status_code=409, detail=f"challenge is {challenge.status}")

        challenge.status = data.status
        challenge.result_json = data.result
        challenge.updated_at = datetime.now()
        self.session.add(challenge)
        self.session.commit()
        self.session.refresh(challenge)
        return challenge

    def cancel_challenge(self, challenge_id: int) -> CaptchaChallenge:
        challenge = self.session.get(CaptchaChallenge, challenge_id)
        if not challenge:
            raise HTTPException(status_code=404, detail="captcha challenge not found")
        challenge.status = CaptchaStatus.CANCELLED
        challenge.updated_at = datetime.now()
        self.session.add(challenge)
        self.session.commit()
        self.session.refresh(challenge)
        return challenge
