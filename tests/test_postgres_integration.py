"""Opt-in: FINFUSION_TEST_DSN must name a disposable finfusion_test_* database.

Creates the finfusion schema only in that explicitly supplied test database.
No existing schema is dropped. Use a new database for each run.
"""
import os
import uuid
from urllib.parse import urlsplit
from decimal import Decimal
import pytest
from finfusion.postgres import PostgresStore, AccountCipher
from finfusion.controls import AccessDenied
from finfusion.models import ServerOrder


@pytest.mark.asyncio
async def test_real_postgres_migration_clients_idempotency_and_restart():
    dsn=os.environ.get("FINFUSION_TEST_DSN")
    if not dsn:
        pytest.skip("A disposable PostgreSQL database has not been supplied")
    if not urlsplit(dsn).path.startswith("/finfusion_test_"):
        pytest.fail("Test DSN must name a fresh finfusion_test_* database")
    cipher=AccountCipher(b"x"*32)
    store=await PostgresStore.connect(dsn,cipher)
    try:
        await store.migrate()
        await store.bind_environment("SANDBOX")
        with pytest.raises(RuntimeError): await store.bind_environment("LIVE")
        uid="test-"+uuid.uuid4().hex
        await store.upsert_user(uid,uid,"test")
        cid,_=await store.register_client(uid,"test","unused-public-key")
        snapshot=await store.configure_client(cid,{"enabled":True,"canRead":True,"canTrade":True,"canCancel":True},"test")
        assert snapshot.clients[cid].can_trade
        account,_=await store.add_broker_account("TEST-"+uuid.uuid4().hex,"test","****0001","test")
        await store.bind_account(uid,account,"test")
        rid=str(uuid.uuid4())
        order=ServerOrder(account,uid,cid,rid,"FFTEST"+uuid.uuid4().hex[:16],"AAPL","BUY","LIMIT",1,"100","100","100","RECEIVED",payload_hash="submit-hash")
        await store.insert(order)
        assert (await store.find_request(account,rid))[1]=="submit-hash"
        replacement=str(uuid.uuid4())
        await store.remember_request(order,replacement,"replace-hash")
        assert (await store.find_request(account,replacement))[1]=="replace-hash"
        order.pending_action="replace"
        await store.update(order,"UNKNOWN")
        await store.consume_nonce(cid,"n"*24)
        await store.close()
        store=await PostgresStore.connect(dsn,cipher)
        await store.migrate()
        assert (await store.find(account,order.client_order_id)).pending_action=="replace"
        with pytest.raises(AccessDenied): await store.consume_nonce(cid,"n"*24)
        snapshot=await store.load_controls(force_global_off=True)
        assert not snapshot.global_trade_enabled
        assert any(o.client_order_id==order.client_order_id for o in await store.unresolved())
    finally:
        await store.close()
