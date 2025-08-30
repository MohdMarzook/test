import os
import threading
import time
import logging
import subprocess
from fastapi import FastAPI
import uvicorn
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("web_worker")

# Load environment variables
if os.path.exists('/etc/secrets/ENV_FILE'):
    load_dotenv('/etc/secrets/ENV_FILE')
else:
    load_dotenv()

# Global variable to track the Celery process
celery_process = None

# Create minimal FastAPI app
app = FastAPI(
    title="PDF Processor",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

@app.get("/")
async def root():
    return {"status": "online"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

def run_celery_worker():
    """Run the Celery worker with automatic restart"""
    global celery_process
    
    max_restarts = 100
    restart_count = 0
    backoff_time = 5
    
    while restart_count < max_restarts:
        try:
            logger.info(f"Starting Celery worker (attempt {restart_count+1}/{max_restarts})")
            
            # Start Celery process
            celery_process = subprocess.Popen([
                "celery", "-A", "task", "worker", 
                "--loglevel=info", 
                "--concurrency=2",
                "--pool=processes"
            ])
            
            # Wait for the process to terminate
            return_code = celery_process.wait()
            
            if return_code == 0:
                logger.info("Celery worker shut down normally")
                break
            
            logger.warning(f"Celery worker crashed with code {return_code}")
            restart_count += 1
            time.sleep(backoff_time)
            backoff_time = min(backoff_time * 2, 60)
            
        except Exception as e:
            logger.error(f"Error managing Celery process: {e}")
            restart_count += 1
            time.sleep(backoff_time)

def main():
    """Run both web server and Celery worker"""
    logger.info("Starting PDF processing service...")
    
    # Start Celery worker in a thread
    celery_thread = threading.Thread(target=run_celery_worker, daemon=True)
    celery_thread.start()
    
    # Run web server in main thread
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=port, 
        log_level="warning",
        workers=1
    )

if __name__ == "__main__":
    main()