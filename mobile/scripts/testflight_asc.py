"""testflight_asc.py <build-number> <whats-new-file>: wait until the build is VALID, add it to group Owner, set What to test."""
import json
import os
import sys
import time
import urllib.error
import urllib.request

import jwt

# Config (env). The .p8 key stays outside the repo and is never committed or printed.
KEY_ID = os.environ.get('ASC_KEY_ID', 'HVML779F7U')
ISSUER = os.environ.get('ASC_ISSUER_ID', '8f9968b2-a219-4890-8574-0822ad510d85')
APP = os.environ.get('ASC_APP_ID', '6820602317')
GROUP = os.environ.get('ASC_BETA_GROUP', 'Owner')
KEY_PATH = os.path.expanduser(os.environ.get('ASC_KEY_PATH', f'~/.appstoreconnect/private_keys/AuthKey_{KEY_ID}.p8'))
bn, wtt = sys.argv[1], open(sys.argv[2]).read().strip()
with open(KEY_PATH) as f:
    k = f.read()


def tok():
    return jwt.encode({'iss': ISSUER, 'iat': int(time.time()), 'exp': int(time.time()) + 600,
                       'aud': 'appstoreconnect-v1'}, k, algorithm='ES256', headers={'kid': KEY_ID})


def call(m, p, b=None):
    r = urllib.request.Request('https://api.appstoreconnect.apple.com' + p, method=m, data=json.dumps(b).encode() if b else None,
                               headers={'Authorization': 'Bearer ' + tok(), 'Content-Type': 'application/json'})
    try:
        x = urllib.request.urlopen(r).read()
        return json.loads(x) if x else {}
    except urllib.error.HTTPError as e:
        return {'err': e.code, 'body': e.read().decode()[:300]}
    except Exception as e:  # network blips: retried by the loop
        return {'err': str(e)}


bid = st = None
for _ in range(120):
    d = call('GET', f'/v1/builds?filter[app]={APP}&filter[version]={bn}&fields[builds]=version,processingState')
    if d.get('data'):
        bid, st = d['data'][0]['id'], d['data'][0]['attributes']['processingState']
        if st == 'VALID':
            break
        if st in ('FAILED', 'INVALID'):
            sys.exit(f'build {bn} {st}')
    time.sleep(20)
print('build', bn, bid, st)
if st != 'VALID':
    sys.exit('not VALID in time')
g = call('GET', f'/v1/betaGroups?filter[app]={APP}&filter[name]={GROUP}')['data'][0]['id']
print(f'group {GROUP}:', call('POST', f'/v1/betaGroups/{g}/relationships/builds', {'data': [{'type': 'builds', 'id': bid}]}) or 'ok')
loc = call('GET', f'/v1/builds/{bid}/betaBuildLocalizations').get('data', [])
if loc:
    r = call('PATCH', '/v1/betaBuildLocalizations/' + loc[0]['id'],
             {'data': {'type': 'betaBuildLocalizations', 'id': loc[0]['id'], 'attributes': {'whatsNew': wtt}}})
else:
    r = call('POST', '/v1/betaBuildLocalizations', {'data': {'type': 'betaBuildLocalizations', 'attributes': {'locale': 'en-US', 'whatsNew': wtt},
                                                            'relationships': {'build': {'data': {'type': 'builds', 'id': bid}}}}})
print('what to test:', r.get('err', 'ok'))
