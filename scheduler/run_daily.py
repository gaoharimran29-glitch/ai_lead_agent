import os
import sys
import logging
import argparse
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from dotenv import load_dotenv

load_dotenv()

# ---------------------------
# Fix import path
# ---------------------------

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)

if project_root not in sys.path:
    sys.path.append(project_root)


# ---------------------------
# Logging Setup
# ---------------------------

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/agent.log"),   # log to file
        logging.StreamHandler(sys.stdout)         # also print to console
    ]
)

logger = logging.getLogger(__name__)


# ---------------------------
# Import Graph
# ---------------------------

try:
    from main import graph
    logger.info("✅ Successfully imported graph from main")
except ImportError as e:
    logger.error(f"❌ ImportError: {e}")
    sys.exit(1)


RUN_HOUR     = int(os.getenv("RUN_HOUR", 9))
RUN_MINUTE   = int(os.getenv("RUN_MINUTE", 0))
RUN_TIMEZONE = os.getenv("RUN_TIMEZONE", "Asia/Kolkata")

def run_agent():
    """
    Invokes the LangGraph pipeline.
    Logs start time, end time, and duration.
    """

    start_time = datetime.now()
    logger.info("=" * 50)
    logger.info(f"🚀 Starting AI Lead Agent at {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)

    try:
        graph.invoke({})

        end_time = datetime.now()
        duration = (end_time - start_time).seconds

        logger.info(f"✅ Run completed successfully in {duration}s")
        logger.info("=" * 50)

    except Exception as e:
        logger.error(f"❌ Agent run failed: {e}", exc_info=True)
        raise   # re-raise so APScheduler listener catches it too


# ---------------------------
# Scheduler Event Listener
# ---------------------------

def job_listener(event):
    """
    Listens to scheduler job outcomes.
    Logs success or failure after every scheduled run.
    """

    if event.exception:
        logger.error(f"❌ Scheduled job FAILED: {event.exception}")
        logger.error("⚠️  Check logs/agent.log for full traceback")
    else:
        logger.info("✅ Scheduled job completed successfully")


# ---------------------------
# Argument Parser
# ---------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="PropTech AI Lead Agent Scheduler"
    )

    parser.add_argument(
        "--no-initial-run",
        action="store_true",
        help="Skip the immediate run on startup. Only run on schedule."
    )

    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run the agent once immediately and exit. No scheduler."
    )

    return parser.parse_args()


# ---------------------------
# Entry Point
# ---------------------------

if __name__ == "__main__":

    args = parse_args()

    # Mode 1 — just run once and exit (useful for testing)
    if args.run_once:
        logger.info("🔁 --run-once flag detected. Running once and exiting.")
        run_agent()
        sys.exit(0)

    # Mode 2 — run immediately + start scheduler
    if not args.no_initial_run:
        logger.info("▶️  Running immediately on startup...")
        run_agent()

    # Start Scheduler
    scheduler = BlockingScheduler(timezone=RUN_TIMEZONE)

    scheduler.add_job(
        run_agent,
        trigger="cron",
        hour=RUN_HOUR,
        minute=RUN_MINUTE,
        id="lead_agent_daily",
        name="PropTech Lead Agent Daily Run",
        misfire_grace_time=300   # if job is late by < 5 min, still run it
    )

    # Attach listener for success/failure events
    scheduler.add_listener(
        job_listener,
        EVENT_JOB_ERROR | EVENT_JOB_EXECUTED
    )

    logger.info(f"⏳ Scheduler started.")
    logger.info(f"📅 Next run: every day at {RUN_HOUR:02d}:{RUN_MINUTE:02d} ({RUN_TIMEZONE})")
    logger.info("Press Ctrl+C to stop.\n")

    try:
        scheduler.start()

    except KeyboardInterrupt:
        logger.info("🛑 Scheduler stopped manually via Ctrl+C")
        scheduler.shutdown(wait=False)
        sys.exit(0)