import uvicorn

from app.startup import configure_logging

if __name__ == "__main__":
    configure_logging()
    uvicorn.run("app.api.main:api", host="0.0.0.0", port=8090, reload=False)
