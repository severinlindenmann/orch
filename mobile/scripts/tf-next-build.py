#!/usr/bin/env python3
"""Print the next TestFlight build number for the orch app: YYMMDD.HHMMSS (UTC), strictly greater than the
latest build in App Store Connect (compared as dotted integers, like TestFlight). Never goes backwards.
Run: uv run --with pyjwt --with cryptography python tf-next-build.py
Config (env): ASC_KEY_PATH (.p8 file, never committed), ASC_KEY_ID, ASC_ISSUER_ID, ASC_APP_ID."""
import datetime
import json
import os
import time
import urllib.request

import jwt

KEY_ID = os.environ.get("ASC_KEY_ID", "HVML779F7U")
ISSUER = os.environ.get("ASC_ISSUER_ID", "8f9968b2-a219-4890-8574-0822ad510d85")
APP = os.environ.get("ASC_APP_ID", "6820602317")
KEY_PATH = os.path.expanduser(os.environ.get("ASC_KEY_PATH", f"~/.appstoreconnect/private_keys/AuthKey_{KEY_ID}.p8"))

with open(KEY_PATH) as f:
    key = f.read()
now = int(time.time())
token = jwt.encode({"iss": ISSUER, "iat": now, "exp": now + 600, "aud": "appstoreconnect-v1"}, key,
                   algorithm="ES256", headers={"kid": KEY_ID})


def get(path):
    req = urllib.request.Request("https://api.appstoreconnect.apple.com" + path, headers={"Authorization": "Bearer " + token})
    return json.load(urllib.request.urlopen(req))


versions = [tuple(int(x) for x in d["attributes"]["version"].split("."))
            for d in get(f"/v1/builds?filter[app]={APP}&limit=200&fields[builds]=version")["data"]]
latest = max(versions) if versions else (0,)
n = datetime.datetime.now(datetime.timezone.utc)
cand = (int(n.strftime("%y%m%d")), int(n.strftime("%H%M%S")))
if cand <= latest:  # clock/date behind a bare or later build: stay on its day, bump the second part
    cand = (latest[0], (latest[1] if len(latest) > 1 else 0) + 1)
print("%d.%d" % cand)
