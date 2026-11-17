"""Real TLS verification through Caddy, then the same full functional smoke test."""
import json
import os
from pathlib import Path
import runpy
import ssl
import time
import urllib.error
import urllib.request

base=os.environ['NBS_TEST_BASE_URL']
ca=Path(os.environ['NBS_TEST_CA'])
deadline=time.monotonic()+60
last_error=None
while time.monotonic()<deadline:
    try:
        context=ssl.create_default_context(cafile=str(ca))
        with urllib.request.urlopen(base+'/api/health',context=context,timeout=5) as response:
            assert json.load(response)['ok']
            assert response.headers.get('Strict-Transport-Security') == 'max-age=31536000'
        break
    except (OSError,ValueError,AssertionError) as exc:
        last_error=exc
        time.sleep(1)
else:
    raise RuntimeError('HTTPS did not become ready with certificate verification enabled') from last_error

with urllib.request.urlopen(base+'/api/auth/state',context=context) as response:
    state=json.load(response)
assert state['configured'] and not state['setup_allowed'] and not state['authenticated']
try:
    urllib.request.urlopen(base+'/api/admin/templates',context=context)
except urllib.error.HTTPError as exc:
    assert exc.code==401
else:
    raise AssertionError('Administrator API was accessible without login')

invalid=urllib.request.Request(base+'/api/auth/login',data=b'{}',
    headers={'Content-Type':'application/json','Origin':'https://invalid.example'})
try:
    urllib.request.urlopen(invalid,context=context)
except urllib.error.HTTPError as exc:
    assert exc.code==403
else:
    raise AssertionError('An invalid origin was accepted')

result=runpy.run_path('/checks/docker_smoke.py',run_name='__main__')
session=next(cookie for cookie in result['cookies'] if cookie.name=='awaji_admin')
assert session.secure and session.has_nonstandard_attr('HttpOnly')
assert session.get_nonstandard_attr('SameSite')=='Strict'
print('PASS: trusted HTTPS, HSTS, protected admin, disabled web setup, Origin validation, Secure/HttpOnly/SameSite cookies.')
