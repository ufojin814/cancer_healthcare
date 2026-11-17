"""本地启动入口：python run.py 后浏览器访问 http://127.0.0.1:8000"""
import uvicorn

from oncopilot.web.app import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
