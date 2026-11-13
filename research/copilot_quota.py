from __future__ import annotations

import asyncio
import json
from research.copilot_backend import data_value, isolated_client, quota_snapshot


async def inspect_quota() -> None:
    client = isolated_client()
    try:
        await asyncio.wait_for(client.start(), timeout=45)
        status = await asyncio.wait_for(client.get_status(), timeout=20)
        auth = await asyncio.wait_for(client.get_auth_status(), timeout=20)
        status_data = data_value(status)
        auth_data = data_value(auth)
        if not isinstance(status_data, dict) or not isinstance(auth_data, dict):
            raise RuntimeError("SDK returned an unsupported status shape; quota was not inferred.")
        print(
            json.dumps(
                {
                    "runtime_version": status_data.get("version"),
                    "authenticated": auth_data.get(
                        "isAuthenticated", auth_data.get("is_authenticated")
                    ),
                    "authentication_method": auth_data.get("authType", auth_data.get("auth_type")),
                    "model_prompts_sent": 0,
                },
                indent=2,
            ),
            flush=True,
        )
        if auth_data.get("isAuthenticated", auth_data.get("is_authenticated")) is not True:
            raise RuntimeError(
                "The SDK runtime is not authenticated. Sign in with the supported Copilot login flow."
            )
        quota = await asyncio.wait_for(quota_snapshot(client), timeout=20)
        quota_data = data_value(quota)
        print(
            json.dumps({"quota": quota_data, "model_prompts_sent": 0}, indent=2, default=str),
            flush=True,
        )
    finally:
        await asyncio.wait_for(client.stop(), timeout=15)


if __name__ == "__main__":
    asyncio.run(inspect_quota())
