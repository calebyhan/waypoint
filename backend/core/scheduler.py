import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.supabase import get_supabase
from services.insights import generate_insights_for_all_workspaces
from services.reconcile import reconcile_all_workspaces

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _reconcile_job():
    db = get_supabase()
    await reconcile_all_workspaces(db)


async def _insights_job():
    db = get_supabase()
    await generate_insights_for_all_workspaces(db)


def start_scheduler():
    scheduler.add_job(_reconcile_job, "interval", minutes=15, id="reconcile")
    scheduler.add_job(_insights_job, "interval", hours=24, id="insights")
    scheduler.start()
    logger.info("Scheduler started: reconcile every 15min, insights every 24h")


def stop_scheduler():
    scheduler.shutdown()
