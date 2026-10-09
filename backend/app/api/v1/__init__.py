from fastapi import APIRouter

from app.api.v1 import admin, auth, me, notifications, timetables

router = APIRouter()
router.include_router(auth.router)
router.include_router(me.router)
router.include_router(timetables.router)
router.include_router(notifications.router)
router.include_router(admin.router)
