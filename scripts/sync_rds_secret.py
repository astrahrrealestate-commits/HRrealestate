#!/usr/bin/env python3
"""Sync rotated RDS master password from AWS RDS secret to EstateOS backend secret."""

import json
import subprocess
import sys
import urllib.parse

REGION = "eu-north-1"
ENVS = {
    "prod": {
        "rds_secret": "rds!db-3744ead8-2cbd-495b-bc80-9571a3e92dca",
        "app_secret": "estateos/prod/backend",
        "cluster": "estateos-prod-cluster",
        "services": ["estateos-prod-api-service", "estateos-prod-worker-service"],
    },
    "stage": {
        "rds_secret": "rds!db-c73eb36c-7d09-4ab0-9b2c-20e2904ab8ad",
        "app_secret": "estateos/stage/backend",
        "cluster": "estateos-stage-cluster",
        "services": ["estateos-stage-api-service", "estateos-stage-worker-service"],
    },
}


def run_aws(args: list[str]) -> str:
    cmd = ["aws"] + args
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def get_secret_json(secret_id: str) -> dict:
    raw = run_aws(
        [
            "secretsmanager",
            "get-secret-value",
            "--secret-id",
            secret_id,
            "--region",
            REGION,
            "--query",
            "SecretString",
            "--output",
            "text",
        ]
    )
    return json.loads(raw)


def sync_env(env: str) -> None:
    cfg = ENVS[env]
    print(f"[{env.upper()}] Reading RDS secret: {cfg['rds_secret']}...")
    rds = get_secret_json(cfg["rds_secret"])
    username = rds["username"]
    password = rds["password"]

    print(f"[{env.upper()}] Reading app secret: {cfg['app_secret']}...")
    app = get_secret_json(cfg["app_secret"])
    old_db_url = app.get("DATABASE_URL", "")

    # Parse existing URL to preserve scheme, host, port, dbname, query
    parsed = urllib.parse.urlsplit(old_db_url)
    encoded_pw = urllib.parse.quote_plus(password)
    port_str = f":{parsed.port}" if parsed.port else ""
    query_str = f"?{parsed.query}" if parsed.query else ""
    new_db_url = f"{parsed.scheme}://{username}:{encoded_pw}@{parsed.hostname}{port_str}{parsed.path}{query_str}"

    if old_db_url == new_db_url:
        print(f"[{env.upper()}] DATABASE_URL is already up-to-date.")
    else:
        app["DATABASE_URL"] = new_db_url
        print(f"[{env.upper()}] Writing updated secret to {cfg['app_secret']}...")
        run_aws(
            [
                "secretsmanager",
                "put-secret-value",
                "--secret-id",
                cfg["app_secret"],
                "--secret-string",
                json.dumps(app, separators=(",", ":")),
                "--region",
                REGION,
            ]
        )
        print(f"[{env.upper()}] Successfully updated DATABASE_URL in {cfg['app_secret']}.")

    print(f"[{env.upper()}] Triggering ECS deployment for services...")
    for svc in cfg["services"]:
        run_aws(
            [
                "ecs",
                "update-service",
                "--cluster",
                cfg["cluster"],
                "--service",
                svc,
                "--force-new-deployment",
                "--region",
                REGION,
            ]
        )
        print(f"[{env.upper()}] Triggered redeploy on {svc}.")


def main() -> None:
    target_env = sys.argv[1] if len(sys.argv) > 1 else "prod"
    if target_env == "all":
        sync_env("prod")
        sync_env("stage")
    elif target_env in ENVS:
        sync_env(target_env)
    else:
        print(f"Unknown env: {target_env}. Use 'prod', 'stage', or 'all'.")
        sys.exit(1)
    print("\nAll requested environments synced and ECS redeployments triggered!")


if __name__ == "__main__":
    main()
