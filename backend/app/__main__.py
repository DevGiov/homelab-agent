import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.api.main:api", host="0.0.0.0", port=8090, reload=False)
