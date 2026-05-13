import uvicorn

from app.core.config import get_settings


def main() -> None:
    get_settings()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8800, reload=True)


if __name__ == "__main__":
    main()
