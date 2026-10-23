"""Use official SDK token operations; emit status only, never token or OTP."""
import contextlib,io,logging,os,sys
from pathlib import Path
os.umask(0o077);logging.disable(logging.CRITICAL)
from webull.core.client import ApiClient
from webull.core.http.initializer.token.token_manager import TokenManager
from webull.core.http.initializer.token.token_operation import TokenOperation
directory=Path('/run/finfusion/secrets/live')
client=ApiClient((directory/'webull_app_key').read_text(),(directory/'webull_app_secret').read_text(),'hk',connect_timeout=8,timeout=12)
client._stream_logger_set=True;client._file_logger_set=True
client.set_token_dir('/var/lib/finfusion/webull_tokens/live')
manager=TokenManager(custom_token_dir='/var/lib/finfusion/webull_tokens/live')
try:
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        local=manager.load_token_from_local()
        operation=TokenOperation(client)
        if local and local.token:
            response=operation.check_token(local.token)
            data=response.json()
            if data.get('status') in {'INVALID','EXPIRED'}:
                response=operation.create_token(None)
                data=response.json()
        else:
            response=operation.create_token(None)
            data=response.json()
        assert response.status_code==200 and data.get('token') and data.get('status')
        manager.save_token_to_local(data)
        manager.token_file_path.chmod(0o600)
    print('Webull LIVE token status: '+str(data['status']),flush=True)
    sys.exit(0 if data['status']=='NORMAL' else 2)
except Exception as exc:
    print('Token bootstrap failed: '+type(exc).__name__,flush=True)
    sys.exit(3)
