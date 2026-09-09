from __future__ import annotations

import uvicorn

from main import runtime_config


if __name__ == "__main__":
    server_config = runtime_config().get("server", {})
    uvicorn.run(
        "main:app",
        host=str(server_config.get("host", "0.0.0.0")),
        port=int(server_config.get("port", 8010)),
        reload=False,
    )
