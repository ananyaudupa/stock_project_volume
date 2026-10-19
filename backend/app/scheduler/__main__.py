"""Single scheduler worker: `python -m app.scheduler`.

Run exactly one instance. Even if two are started by mistake, the scan-run claim in
services/scanner.py ensures each scan executes and publishes at most once.
"""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.models import ScanSession
from app.scheduler.jobs import missing_scan_watchdog, performance_job, scheduled_scan_job


def main() -> None:
    configure_logging()
    s = get_settings()
    log = logging.getLogger("scheduler")
    sched = BlockingScheduler(timezone=s.tz, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 600})

    def cron(t):
        return CronTrigger(day_of_week="mon-fri", hour=t.hour, minute=t.minute, timezone=s.tz)

    sched.add_job(scheduled_scan_job, cron(s.morning_scan_time), args=[ScanSession.MORNING], id="scan-morning")
    sched.add_job(scheduled_scan_job, cron(s.afternoon_scan_time), args=[ScanSession.AFTERNOON], id="scan-afternoon")
    sched.add_job(performance_job, cron(s.performance_job_time), id="performance-close")
    sched.add_job(missing_scan_watchdog, CronTrigger(day_of_week="mon-fri", hour="9-16", minute="*/10", timezone=s.tz),
                  id="missing-scan-watchdog")

    log.info("scheduler starting", extra={"jobs": [j.id for j in sched.get_jobs()], "timezone": s.timezone})
    sched.start()


if __name__ == "__main__":
    main()
