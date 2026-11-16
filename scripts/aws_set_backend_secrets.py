#!/usr/bin/env python3
"""Put provider secrets into the AWS backend secret without them appearing on screen, in shell history or in a chat.

Usage (from the repo root, with AWS credentials for the EstateOS account in your environment):

    uv run --project backend python scripts/aws_set_backend_secrets.py --env prod
    uv run --project backend python scripts/aws_set_backend_secrets.py --env stage --keys BRIXX_TOKEN

For each key it asks with a hidden prompt (press Enter to keep the current value). WHATSAPP_VERIFY_TOKEN can be
generated instead of typed; the script then prints it once, because it must be pasted into the Meta webhook settings
together with the callback URL it prints. The secret JSON is read, merged and written back (other keys untouched);
nothing else is printed. Afterwards it force-redeploys the env's api and worker services so they load the new values.
"""

import argparse
import getpass
import json
import secrets
import sys

import boto3

REGION = "eu-north-1"
DEFAULT_KEYS = ("WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN", "BRIXX_TOKEN")
API_HOSTS = {"prod": "api-estateos.hrrealestate.nl", "stage": "api-stage-estateos.hrrealestate.nl"}


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


def _ask(key: str, has_value: bool) -> str | None:
    state = "set" if has_value else "EMPTY"
    if key == "WHATSAPP_VERIFY_TOKEN":
        answer = input(f"{key} is {state}. Generate a new random one? [y/N] ").strip().lower()
        if answer == "y":
            return secrets.token_urlsafe(32)
    value = getpass.getpass(f"{key} is {state}. New value (hidden, Enter keeps it): ").strip()
    return value or None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env", choices=sorted(API_HOSTS), required=True)
    parser.add_argument("--keys", default=",".join(DEFAULT_KEYS), help="comma separated secret keys to set")
    parser.add_argument("--no-redeploy", action="store_true", help="only write the secret")
    args = parser.parse_args()

    name = f"estateos/{args.env}/backend"
    client = boto3.client("secretsmanager", region_name=REGION)
    current = json.loads(client.get_secret_value(SecretId=name)["SecretString"])
    changed: dict[str, str] = {}
    for key in [k.strip() for k in args.keys.split(",") if k.strip()]:
        value = _ask(key, bool(current.get(key)))
        if value is not None:
            changed[key] = value
    if not changed:
        _say("Nothing changed.")
        return 0
    client.put_secret_value(SecretId=name, SecretString=json.dumps({**current, **changed}))
    _say(f"Updated {name}: {', '.join(sorted(changed))}")
    if "WHATSAPP_VERIFY_TOKEN" in changed:
        _say("\nMeta app > WhatsApp > Configuration > Webhook:")
        _say(f"  Callback URL: https://{API_HOSTS[args.env]}/webhooks/whatsapp")
        _say(f"  Verify token: {changed['WHATSAPP_VERIFY_TOKEN']}")
        _say("  Subscribe to the `messages` field.")
    if not args.no_redeploy:
        ecs = boto3.client("ecs", region_name=REGION)
        cluster = f"estateos-{args.env}-cluster"
        for service in (f"estateos-{args.env}-api-service", f"estateos-{args.env}-worker-service"):
            ecs.update_service(cluster=cluster, service=service, forceNewDeployment=True)
        _say(f"Redeploying {cluster} api and worker so they read the new values (about 3 minutes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
