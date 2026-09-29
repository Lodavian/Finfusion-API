"""Generate the checked-in OpenAPI contract. No running service required."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
schemas={
    "Error":{"type":"object","required":["error"],"properties":{"error":{"type":"object","required":["code","message"],"properties":{"code":{"type":"string"},"message":{"type":"string"}}}}},
    "OrderInput":{"type":"object","additionalProperties":False,"required":["accountRef","symbol","side","orderType","quantity"],"properties":{
        "accountRef":{"type":"string"},"symbol":{"type":"string","pattern":"^[A-Z][A-Z0-9.\\-]{0,9}$"},
        "side":{"type":"string","enum":["BUY","SELL"]},"orderType":{"type":"string","enum":["MARKET","LIMIT"]},
        "quantity":{"type":"integer","minimum":1},"limitPrice":{"type":"string","description":"Positive decimal; required for LIMIT; omit for MARKET"}}},
    "Order":{"type":"object","properties":{key:{"type":typ} for key,typ in {
        "accountRef":"string","clientOrderId":"string","requestId":"string","status":"string","version":"integer","symbol":"string","side":"string","orderType":"string","quantity":"integer","message":"string","createdAt":"number","updatedAt":"number"}.items()}},
    "OrderEvent":{"type":"object","required":["type","order"],"properties":{"type":{"type":"string","enum":["order.update"]},"eventId":{"type":"string"},"occurredAt":{"type":"string","format":"date-time"},"order":{"$ref":"#/components/schemas/Order"}}},
    "Positions":{"type":"object","properties":{"accountRef":{"type":"string"},"positions":{"type":"array","items":{"type":"object","properties":{k:{"type":"string"} for k in ["symbol","name","lastPrice","quantity","unitCost","unrealizedPnl"]}}}}},
    "Balance":{"type":"object","properties":{"accountRef":{"type":"string"},"currency":{"type":"string","enum":["USD"]},"usdBuyingPower":{"type":"string","nullable":True}}},
    "Accounts":{"type":"object","properties":{"accounts":{"type":"array","items":{"type":"object","properties":{"accountRef":{"type":"string"},"alias":{"type":"string"},"accountMask":{"type":"string"},"tradeEnabled":{"type":"boolean"},"controlVersion":{"type":"integer"}}}}}},
    "OrderList":{"type":"object","properties":{"orders":{"type":"array","items":{"$ref":"#/components/schemas/Order"}},"nextCursor":{"type":"string","nullable":True}}},
}
schemas["Order"]["properties"].update(limitPrice={"type":"string","nullable":True},pendingAction={"type":"string","nullable":True})


def body(properties, required=None):
    return {"type":"object","additionalProperties":False,"properties":properties,"required":list(properties) if required is None else required}


S={"type":"string"}; B={"type":"boolean"}
operations=[
    ("get","/livez","Process liveness",None,None),
    ("get","/readyz","Trading infrastructure readiness",None,None),
    ("get","/v1/accounts","List authorized accounts",None,"Accounts"),
    ("get","/v1/accounts/{account_ref}/positions","USD stock and ETF positions",None,"Positions"),
    ("get","/v1/accounts/{account_ref}/balance","USD buying power",None,"Balance"),
    ("post","/v1/orders","Submit an order",{"$ref":"#/components/schemas/OrderInput"},"OrderEvent"),
    ("patch","/v1/orders/{client_order_id}","Replace limit price",body({"accountRef":S,"limitPrice":S}),"OrderEvent"),
    ("post","/v1/orders/{client_order_id}/cancel","Cancel order",body({"accountRef":S}),"OrderEvent"),
    ("get","/v1/orders","List orders",None,"OrderList"),
    ("get","/v1/orders/{client_order_id}","Get order",None,"Order"),
    ("get","/v1/requests/{request_id}","Get original request result",None,"OrderEvent"),
    ("get","/v1/events","Signed read-only WebSocket order events",None,None),
    ("post","/v1/symbols/select","Optional quote warm-up",body({"accountRef":S,"symbol":S}),None),
    ("get","/admin/config","Public administrator OIDC configuration",None,None),
    ("get","/admin/v1/state","Administrator state",None,None),
    ("post","/admin/v1/users","Create managed user",body({"username":S,"displayName":S,"password":S}),None),
    ("post","/admin/v1/users/{user_id}/status","Enable or disable user",body({"enabled":B}),None),
    ("post","/admin/v1/users/{user_id}/password","Reset managed user password",body({"password":S}),None),
    ("post","/admin/v1/accounts","Register discovered broker account",body({"brokerAccountId":S,"alias":S}),None),
    ("post","/admin/v1/bindings","Bind account to one user",body({"userId":S,"accountRef":S}),None),
    ("post","/admin/v1/bindings/{account_ref}/remove","Remove account authorization",body({}),None),
    ("post","/admin/v1/clients","Register public key; pending approval",body({"userId":S,"label":S,"publicKeyPem":S}),None),
    ("patch","/admin/v1/clients/{client_id}","Permissions or key rotation; rotation disables client",body({"enabled":B,"publicKeyPem":S,"canRead":B,"canTrade":B,"canCancel":B},[]),None),
    ("post","/admin/v1/clients/{client_id}","Enable or disable client",body({"enabled":B}),None),
    ("post","/admin/v1/controls/{scope}","Set global, user or account trade gate",body({"key":S,"enabled":B,"reason":S},["enabled"]),None),
]


def generate():
    import re
    paths={}
    for method,path,title,request,response in operations:
        admin=path.startswith("/admin/v1/"); signed=path.startswith("/v1/")
        code="101" if path=="/v1/events" else "202" if method in {"post","patch"} and path.startswith("/v1/orders") else "201" if method=="post" and path in {"/admin/v1/users","/admin/v1/accounts","/admin/v1/bindings","/admin/v1/clients"} else "200"
        op={"summary":title,"operationId":method+"_"+re.sub(r"[^a-zA-Z0-9]+","_",path).strip("_"),"security":[{"AdminBearer":[]}] if admin else [{"ClientId":[],"ClientSignature":[]}] if signed else [],"parameters":[],"responses":{code:{"description":title}}}
        for parameter in re.findall(r"\{([^}]+)\}",path):
            op["parameters"].append({"name":parameter,"in":"path","required":True,"schema":S})
        if signed:
            for name in ["X-Timestamp","X-Nonce"]:
                op["parameters"].append({"name":name,"in":"header","required":True,"schema":S})
        if method in {"post","patch"} and path.startswith("/v1/orders"):
            op["parameters"].append({"name":"Idempotency-Key","in":"header","required":True,"schema":{"type":"string","format":"uuid"}})
        if method=="get" and (path.startswith("/v1/requests/") or path.startswith("/v1/orders")):
            op["parameters"].append({"name":"accountRef","in":"query","required":path!="/v1/orders","schema":S})
        if path=="/v1/orders" and method=="get":
            op["parameters"] += [{"name":"limit","in":"query","schema":{"type":"integer","minimum":1,"maximum":200,"default":50}},{"name":"cursor","in":"query","schema":S}]
        if request: op["requestBody"]={"required":True,"content":{"application/json":{"schema":request}}}
        if response: op["responses"][code]["content"]={"application/json":{"schema":{"$ref":"#/components/schemas/"+response}}}
        for error in ["400","403","409","429","500","503"]:
            op["responses"][error]={"description":"See error.code and docs/API.md","content":{"application/json":{"schema":{"$ref":"#/components/schemas/Error"}}}}
        paths.setdefault(path,{})[method]=op
    return {"openapi":"3.0.3","info":{"title":"Finfusion API","version":"0.1.0","description":"P-256 signed program API; administrator login is separate. See API.md for canonical signing and timeout recovery."},"servers":[{"url":"https://api.example.com"}],"paths":paths,"components":{"schemas":schemas,"securitySchemes":{"ClientId":{"type":"apiKey","in":"header","name":"X-Client-Id"},"ClientSignature":{"type":"apiKey","in":"header","name":"X-Client-Signature"},"AdminBearer":{"type":"http","scheme":"bearer","bearerFormat":"JWT"}}}}


if __name__=="__main__":
    (ROOT/"docs/openapi.json").write_text(json.dumps(generate(),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
