import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from database import engine, Base
from bot import application
from scheduler import run_scheduler_loop

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Background tasks tracking
bg_tasks = set()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup Actions ---
    logger.info("Initializing database...")
    Base.metadata.create_all(bind=engine)
    
    if application:
        logger.info("Starting Telegram Bot...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        logger.info("Starting background scheduler...")
        task = asyncio.create_task(run_scheduler_loop(application))
        bg_tasks.add(task)
        task.add_done_callback(bg_tasks.discard)
    else:
        logger.warning(
            "TELEGRAM_BOT_TOKEN is not set or set to default value in .env. "
            "Telegram Bot and scheduler tasks are NOT running. "
            "Please configure the .env file."
        )
        
    yield
    
    # --- Shutdown Actions ---
    if application:
        logger.info("Stopping Telegram Bot...")
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        logger.info("Telegram Bot stopped.")
        
    # Cancel remaining background tasks
    for task in list(bg_tasks):
        task.cancel()
    logger.info("Application shutdown complete.")

app = FastAPI(
    title="Office Work Tracker Bot Service",
    description="FastAPI service hosting the work and break tracking Telegram Bot.",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/")
def read_root():
    return {
        "status": "online",
        "service": "Office Work Tracker Bot",
        "bot_active": application is not None
    }
