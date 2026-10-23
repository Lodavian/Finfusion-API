"""Deployment boundary, independent of account permissions and risk checks."""
import json
from aiohttp import web


@web.middleware
async def readonly_perimeter(request, handler):
    if request.method not in {'GET','HEAD','OPTIONS'}:
        deny = request.path.startswith('/v1/orders')
        if request.path.startswith('/admin/v1/'):
            try: payload = json.loads(await request.read())
            except (ValueError,UnicodeError): payload = {}
            if isinstance(payload,dict):
                if request.path.startswith('/admin/v1/controls/'):
                    deny = deny or payload.get('enabled') is True
                if request.path.startswith('/admin/v1/clients/'):
                    deny = deny or payload.get('canTrade') is True or payload.get('canCancel') is True
        if deny:
            return web.json_response({'error': {'code':'READ_ONLY_DEPLOYMENT',
                'message':'当前部署仅允许管理与只读查询，交易及交易权限提升已禁用'}},status=403)
    return await handler(request)
