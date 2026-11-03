import uvicorn

if __name__ == "__main__":
    # The SQLite pilot and engine jobs require a single process.
    uvicorn.run("server.app:create_app", factory=True, host="0.0.0.0", port=8080, workers=1, access_log=False)

