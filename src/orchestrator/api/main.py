"""`orchestrator-api` console entry point."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "orchestrator.api.app:app_factory",
        factory=True,
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        proxy_headers=True,
        log_config=None,
    )


if __name__ == "__main__":
    main()
