"""Poll the PostgreSQL screening ledger from a dedicated worker process."""
import asyncio
import logging
import signal
from datetime import timedelta

from sqlalchemy import and_, or_, select, text

from talentforge.config import get_settings
from talentforge.cv_automation import QUEUE_PREFIX, process_application, webhook_configuration
from talentforge.database import SessionLocal, engine
from talentforge.models import AuditEvent, CVScreening, utcnow

logger = logging.getLogger(__name__)


async def run_once(slot: int) -> bool:
    """Keep a PostgreSQL session lock for the entire attempt, without an open transaction."""
    with engine.connect() as connection:
        try:
            acquired = connection.scalar(
                text("SELECT pg_try_advisory_lock(84021, :slot)"), {"slot": slot}
            )
            connection.commit()
            if not acquired:
                return False
            now = utcnow()
            cutoff = now - timedelta(seconds=60)
            with SessionLocal() as db:
                row = db.execute(
                    select(CVScreening.application_id, CVScreening.state)
                    .where(
                        CVScreening.generation_token.startswith(QUEUE_PREFIX),
                        or_(
                            CVScreening.state == "queued",
                            and_(CVScreening.state == "extracting", CVScreening.lease_until <= now),
                            and_(get_settings().n8n_auto_dispatch_enabled,
                                 CVScreening.state == "ready", CVScreening.error_code.is_(None)),
                            and_(CVScreening.state == "dispatching", CVScreening.dispatch_started_at <= cutoff),
                        ),
                    )
                    .order_by(CVScreening.created_at, CVScreening.application_id)
                    .limit(1)
                ).first()
            if row is None:
                return False
            application_id, state = row
            if not connection.scalar(
                text("SELECT pg_try_advisory_lock(hashtextextended(:application_id, 84021))"),
                {"application_id": application_id},
            ):
                return False
            connection.commit()
            if state == "dispatching":
                with SessionLocal() as db:
                    item = db.scalar(select(CVScreening).where(
                        CVScreening.application_id == application_id,
                        CVScreening.state == "dispatching",
                        CVScreening.dispatch_started_at <= cutoff,
                    ).with_for_update())
                    if item:
                        item.state = "unknown"
                        item.error_code = "webhook_delivery_uncertain"
                        db.add(AuditEvent(action="webhook_delivery_uncertain",
                                          entity_type="cv_screening", entity_id=application_id))
                        db.commit()
            else:
                await process_application(application_id, durable=True)
            return True
        finally:
            # Session locks must never go back to the connection pool.
            try:
                connection.rollback()
                connection.execute(text("SELECT pg_advisory_unlock_all()"))
                connection.commit()
            except Exception:
                connection.invalidate()


async def serve():
    settings = get_settings()
    if not (settings.cv_automation_enabled and settings.cv_durable_queue_enabled):
        raise SystemExit("Enable CV automation and its durable queue before starting the worker.")
    if engine.dialect.name != "postgresql":
        raise SystemExit("The CV worker requires PostgreSQL.")
    if settings.n8n_auto_dispatch_enabled:
        webhook_configuration()
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopping.set)

    async def poll(slot):
        while not stopping.is_set():
            try:
                if await run_once(slot):
                    continue
            except Exception as error:
                logger.warning("CV worker poll failed error_type=%s", type(error).__name__)
            try:
                await asyncio.wait_for(stopping.wait(), timeout=1)
            except TimeoutError:
                pass

    await asyncio.gather(*(poll(slot) for slot in range(1, settings.cv_worker_concurrency + 1)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
