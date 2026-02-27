from backend.main import app
import uvicorn
import os
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    port = int(os.environ.get("MNESIS_PORT", 7860))
    # Default to loopback for desktop mode; set MNESIS_HOST=0.0.0.0 for server/Docker mode
    host = os.environ.get("MNESIS_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port)
