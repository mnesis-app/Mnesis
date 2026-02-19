from backend.main import app
import uvicorn
import os
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    port = int(os.environ.get("MNESIS_PORT", 7860))
    # Bind to 127.0.0.1 explicitly to avoid firewall issues
    uvicorn.run(app, host="127.0.0.1", port=port)
