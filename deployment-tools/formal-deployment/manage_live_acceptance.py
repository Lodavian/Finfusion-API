"""Real administrator API acceptance, with root-only credentials and no orders."""
import argparse,asyncio,base64,contextlib,hashlib,io,json,logging,os,secrets,sys,urllib.error,urllib.parse,urllib.request
from pathlib import Path
os.umask(0o077);logging.disable(logging.CRITICAL)
root=Path('/var/lib/finfusion/formal-deployment/live')
credentials=json.loads(Path('/var/lib/finfusion/casdoor-bootstrap/credentials.json').read_text())
origin='http://127.0.0.1:8081';auth=credentials['url']
def call(url,payload=None,method=None,token=None):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=urllib.request.Request(url,data=None if payload is None else json.dumps(payload).encode(),method=method,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=25) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as e:return e.code,json.load(e)
def admin_token():
    verifier=secrets.token_urlsafe(48);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    query=urllib.parse.urlencode({'clientId':credentials['clientId'],'responseType':'code','redirectUri':origin+'/admin/','scope':'openid profile','state':secrets.token_urlsafe(16),'code_challenge_method':'S256','code_challenge':challenge})
    c=credentials['finfusionAdmin']
    status,r=call(auth+'/api/login?'+query,{'application':'finfusion-admin','organization':'finfusion','username':c['username'],'password':c['password'],'type':'code','signinMethod':'Password'})
    assert status==200 and r.get('status')=='ok','Admin OAuth login failed'
    status,r=call(auth+'/api/login/oauth/access_token',{'grant_type':'authorization_code','client_id':credentials['clientId'],'code':r['data'],'code_verifier':verifier,'redirect_uri':origin+'/admin/'})
    assert status==200 and r.get('access_token'),'Admin token exchange failed'
    return r['access_token']
token=admin_token()
def api(path,payload=None,method=None,expected=200):
    status,r=call(origin+path,payload,method,token)
    assert status==expected,f'Management API {path} returned HTTP {status}'
    return r
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['provision','approve','disable-user','enable-user','revoke-client','restore-client','add-accounts','assert-readonly']);args=parser.parse_args()
context_path=root/'acceptance.json'
context=json.loads(context_path.read_text()) if context_path.exists() else {'username':'windows-readonly','password':'Aa7_'+secrets.token_urlsafe(24)}
def save():context_path.write_text(json.dumps(context,indent=2));context_path.chmod(0o600)
if args.action=='provision':
    save()
    snapshot=api('/admin/v1/state')
    found=next((u for u in snapshot['users'] if u['casdoor_name']==context['username']),None)
    if found:context['userId']=found['user_id']
    else:context['userId']=api('/admin/v1/users',{'username':context['username'],'displayName':'Windows 只读用户','password':context['password']},expected=201)['userId']
    existing=next((c for c in snapshot['clients'] if c['user_id']==context['userId'] and c['label']=='Windows 只读工作站'),None)
    if existing:context['clientId']=existing['client_id']
    else:
        public=json.loads(Path('/home/finfusion_tech/formal-deployment/live-client-registration.json').read_text())
        result=api('/admin/v1/clients',{'userId':context['userId'],'label':public['label'],'publicKeyPem':public['publicKeyPem']},expected=201)
        assert result['status']=='PENDING_ADMIN_APPROVAL';context['clientId']=result['clientId']
    api('/admin/v1/controls/user',{'key':context['userId'],'enabled':False,'reason':'LIVE read-only acceptance'})
    save();print('PASS: actual Casdoor user created and real Windows public key registered, pending approval.')
elif args.action in {'approve','restore-client'}:
    api('/admin/v1/clients/'+context['clientId'],{'enabled':True,'canRead':True,'canTrade':False,'canCancel':False},'PATCH')
    print('PASS: client approved for read only; trading and cancellation denied.')
elif args.action in {'disable-user','enable-user'}:
    api('/admin/v1/users/'+context['userId']+'/status',{'enabled':args.action=='enable-user'})
    print('PASS: managed user status updated through actual Casdoor and Finfusion API.')
elif args.action=='revoke-client':
    api('/admin/v1/clients/'+context['clientId'],{'enabled':False},'PATCH');print('PASS: client revoked via real management API.')
elif args.action=='add-accounts':
    sys.path.insert(0,'/opt/finfusion/current')
    from finfusion.gateway import GatewayConfig,InstitutionalWebullGateway
    from finfusion_common.utils import rows_from,response_ok
    async def discover():
        p=Path('/run/finfusion/secrets/live')
        gateway=InstitutionalWebullGateway(GatewayConfig((p/'webull_app_key').read_text(),(p/'webull_app_secret').read_text(),Path('/var/lib/finfusion/webull_tokens/live')))
        try:
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                await gateway._call(gateway._build_clients);response=await gateway._call(gateway.trade_client.account_v2.get_account_list)
            assert response_ok(response)
            return [str(r.get('account_id') or r.get('accountId') or r.get('id')) for r in rows_from(response) if r.get('account_id') or r.get('accountId') or r.get('id')]
        finally:await gateway.close()
    accounts=asyncio.run(discover());snapshot=api('/admin/v1/state')
    if not snapshot['accounts']:
        context['accountRefs']=[]
        for number,account in enumerate(accounts,1):
            ref=api('/admin/v1/accounts',{'brokerAccountId':account,'alias':f'Webull HK 账户 {number}'},expected=201)['accountRef']
            api('/admin/v1/bindings',{'userId':context['userId'],'accountRef':ref},expected=201)
            api('/admin/v1/controls/account',{'key':ref,'enabled':False,'reason':'LIVE read-only acceptance'})
            context['accountRefs'].append(ref)
        save()
    print('PASS: discovered real accounts registered and assigned; account trading remains off. Count:',len(accounts))
elif args.action=='assert-readonly':
    snapshot=api('/admin/v1/state');assert not snapshot['control']['global_trade_enabled']
    c=next(x for x in snapshot['clients'] if x['client_id']==context['clientId'])
    assert c['enabled'] and c['can_read'] and not c['can_trade'] and not c['can_cancel']
    assert all(not u['trade_enabled'] for u in snapshot['users'])
    assert all(not a['trade_enabled'] for a in snapshot['accounts'])
    # No order-shaped requests are sent to the real server. Permission escalation
    # is checked through the admin perimeter, and order blocking via unit tests.
    for path,payload,method in [('/admin/v1/controls/global',{'enabled':True},'POST'),('/admin/v1/clients/'+context['clientId'],{'canTrade':True},'PATCH'),('/admin/v1/clients/'+context['clientId'],{'canCancel':True},'PATCH')]:
        status,r=call(origin+path,payload,method,token)
        assert status==403 and r.get('error',{}).get('code')=='READ_ONLY_DEPLOYMENT'
    print('PASS: global/user/account trading is off; actual server rejects permission escalation.')
