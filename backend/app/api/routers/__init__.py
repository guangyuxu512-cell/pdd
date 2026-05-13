from fastapi import APIRouter

from app.api.routers import ai, browser, captcha, config, health, logs, products, pxi, shops, shunshou, tasks

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(shops.router)
api_router.include_router(products.router)
api_router.include_router(pxi.router)
api_router.include_router(shunshou.router)
api_router.include_router(browser.router)
api_router.include_router(tasks.router)
api_router.include_router(logs.router)
api_router.include_router(captcha.router)
api_router.include_router(ai.router)
api_router.include_router(config.router)
