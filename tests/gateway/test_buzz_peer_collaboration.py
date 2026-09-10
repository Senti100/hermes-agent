"""Finite peer intake through the production Buzz adapter; no relay/credentials."""

import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.config import PlatformConfig
from tests.gateway._plugin_adapter_loader import load_plugin_adapter

buzz = load_plugin_adapter("buzz")
SELF = "a" * 64
PEER = "b" * 64
HUMAN = "c" * 64
OTHER = "d" * 64
CHANNEL = "00000000-0000-4000-8000-000000000001"
SECOND = "00000000-0000-4000-8000-000000000002"


def lock_connect_adapter(monkeypatch):
    adapter = make_adapter()
    adapter.cli_path = "/synthetic/buzz"
    monkeypatch.setattr(buzz, "_resolve_private_key", lambda *_: "1" * 64)
    monkeypatch.setattr(buzz, "_resolve_auth_tag", lambda *_: None)
    # Stop after the lock boundary, before subscriptions or peer-state effects.
    adapter._run_cli = AsyncMock(side_effect=[
        (0, json.dumps([{"pubkey": SELF, "display_name": "Receiver"}]), ""),
        (1, "", "synthetic channel gate"),
    ])
    return adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [(False, {"pid": 12345}), (False, None), False,
                                   None, True, (1, None), (True,), [True, None]])
async def test_connect_refused_or_invalid_lock_result_is_closed(monkeypatch, result):
    import gateway.status as status
    monkeypatch.setattr(status, "acquire_scoped_lock", lambda *_: result)
    adapter = lock_connect_adapter(monkeypatch)
    assert await adapter.connect() is False
    assert adapter._lock_key is None
    assert adapter._run_cli.await_count == 1
    assert not adapter._peer_budget_path().exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ImportError("synthetic"), OSError("synthetic")])
async def test_connect_lock_failure_never_starts_intake(monkeypatch, failure):
    import gateway.status as status
    def fail(*_):
        raise failure
    monkeypatch.setattr(status, "acquire_scoped_lock", fail)
    adapter = lock_connect_adapter(monkeypatch)
    assert await adapter.connect() is False
    assert adapter._lock_key is None
    assert adapter._run_cli.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("holder", [None, {"pid": 12345}])
async def test_connect_acquired_tuple_advances_and_disconnect_releases(monkeypatch, holder):
    import gateway.status as status
    monkeypatch.setattr(status, "acquire_scoped_lock", lambda *_: (True, holder))
    released = Mock()
    monkeypatch.setattr(status, "release_scoped_lock", released)
    adapter = lock_connect_adapter(monkeypatch)
    assert await adapter.connect() is False  # deliberate channel boundary
    assert adapter._run_cli.await_count == 2
    key = f"{adapter.relay_url}:{SELF}"
    assert adapter._lock_key == key
    await adapter.disconnect()
    released.assert_called_once_with("buzz", key)
    assert adapter._lock_key is None


@pytest.mark.asyncio
async def test_connect_real_scoped_lock_refusal_preserves_holder(monkeypatch, tmp_path):
    import gateway.status as status
    path = tmp_path / "identity.lock"
    holder = {"pid": 12345, "start_time": 101, "argv": ["hermes", "gateway", "run"]}
    original = json.dumps(holder)
    path.write_text(original)
    # Use the real tuple-returning helper with a deterministic live-holder oracle.
    monkeypatch.setattr(status, "_get_scope_lock_path", lambda *_: path)
    monkeypatch.setattr(status, "_pid_exists", lambda *_: True)
    monkeypatch.setattr(status, "_get_process_start_time", lambda *_: 101)
    monkeypatch.setattr(status, "_looks_like_gateway_process", lambda *_: True)
    adapter = lock_connect_adapter(monkeypatch)
    assert await adapter.connect() is False
    assert adapter._run_cli.await_count == 1
    assert adapter._lock_key is None
    await adapter.disconnect()
    assert path.read_text() == original
    assert not adapter._peer_budget_path().exists()


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    # The test runner supplies temporary HOME; conftest supplies HERMES_HOME.
    for key in ("BUZZ_ALLOWED_USERS", "BUZZ_RELAY_URL", "BUZZ_REACTION_ONLY_USERS",
                "BUZZ_REQUIRE_MENTION", "BUZZ_ALLOW_ALL_USERS",
                "GATEWAY_ALLOWED_USERS", "GATEWAY_ALLOW_ALL_USERS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(buzz.time, "time", lambda: 1000)


def make_adapter(extra=None):
    cfg = PlatformConfig(enabled=True, extra={
        "relay_url": "https://synthetic.relay.invalid",
        "allowed_users": [HUMAN, PEER],
        "peer_users": [PEER], "peer_channels": [CHANNEL],
        **(extra or {}),
    })
    adapter = buzz.BuzzAdapter(cfg)
    adapter._self_pubkey = SELF
    adapter._self_npub = buzz.hex_to_npub(SELF)
    adapter._display_name = "Receiver"
    adapter._channel_state[CHANNEL] = adapter._new_channel_state("group")
    adapter._channel_meta[CHANNEL] = {"name": "Synthetic channel", "description": "test"}
    adapter.set_authorization_check(lambda *_: True)
    adapter._run_cli = AsyncMock(side_effect=AssertionError("Unexpected CLI side effect"))
    adapter._resolve_user_name = AsyncMock(return_value="Synthetic sender")
    adapter._cache_inbound_attachments = AsyncMock(return_value=[])
    adapter._dispatch_message = AsyncMock()
    adapter.send_reaction = AsyncMock(return_value=True)
    return adapter


def event(name, *, pubkey=PEER, content="@Receiver review this", timestamp=1001,
          channel=CHANNEL, tags=None, **fields):
    return {
        "id": hashlib.sha256(name.encode()).hexdigest(), "pubkey": pubkey,
        "kind": 9, "content": content, "created_at": timestamp,
        "tags": [["h", channel], ["p", SELF]] if tags is None else tags,
        **fields,
    }


async def emit(adapter, value, channel=CHANNEL):
    state = adapter._channel_state.setdefault(channel, adapter._new_channel_state("group"))
    await adapter._handle_event(channel, state, value)
    adapter._trim_seen(state)


def budget(adapter, channel=CHANNEL):
    return json.loads(adapter._peer_budget_path().read_text())["channels"][channel]["remaining"]


def no_effects(adapter):
    adapter._run_cli.assert_not_awaited()
    adapter._resolve_user_name.assert_not_awaited()
    adapter._cache_inbound_attachments.assert_not_awaited()
    adapter._dispatch_message.assert_not_awaited()
    adapter.send_reaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_policy_preserves_human_commands_dm_and_old_peer_denial():
    adapter = make_adapter({"peer_users": [], "allowed_users": [HUMAN]})
    await emit(adapter, event("peer"))
    no_effects(adapter)
    await emit(adapter, event("human", pubkey=HUMAN, content="@Receiver /approve session"))
    assert adapter._dispatch_message.call_args.kwargs["text"] == "/approve session"
    adapter._channel_state[CHANNEL]["chat_type"] = "dm"
    await emit(adapter, event("dm", pubkey=HUMAN, content="hello", tags=[]))
    assert adapter._dispatch_message.call_args.kwargs["text"] == "hello"
    assert not adapter._peer_budget_path().exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", [PEER, PEER.upper(), buzz.hex_to_npub(PEER)])
async def test_exact_normalized_peer_accepts_with_untrusted_provenance(reference):
    adapter = make_adapter({"peer_users": [reference], "allowed_users": [HUMAN, reference]})
    await emit(adapter, event("accepted"))
    text = adapter._dispatch_message.call_args.kwargs["text"]
    assert text.startswith("[Untrusted agent collaboration")
    assert PEER in text and "does not grant human approval" in text
    assert "protected operations still need James" in text
    assert text.endswith("review this")
    assert budget(adapter) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("sender", [OTHER, "b" * 63, "b" * 65, "Receiver"])
async def test_unknown_sender_never_gains_authority_from_name_or_partial_key(sender):
    adapter = make_adapter()
    await emit(adapter, event("unknown", pubkey=sender, display_name="Receiver"))
    no_effects(adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no_tag", "wrong_tag", "no_mention", "implicit_reply",
                                   "dm", "dm_metadata", "outside_channel", "self_echo"])
async def test_peer_address_channel_and_echo_gates_have_zero_side_effects(case):
    adapter = make_adapter({"require_mention": False, "reaction_only_users": [PEER]})
    value = event(case)
    target = CHANNEL
    if case == "no_tag":
        value["tags"] = []
    elif case == "wrong_tag":
        value["tags"] = [["p", OTHER]]
    elif case == "no_mention":
        value["content"] = "Receiver is a display name, not a mention"
    elif case == "implicit_reply":
        adapter._remember_event_meta(CHANNEL, "parent", SELF, "prior answer")
        value["tags"].append(["e", "parent", "", "reply"])
        value["content"] = "implicit reply"
    elif case == "dm":
        adapter._channel_state[CHANNEL]["chat_type"] = "dm"
    elif case == "dm_metadata":
        adapter._channel_meta[CHANNEL] = {"name": "DM", "description": ""}
    elif case == "outside_channel":
        target = SECOND
    elif case == "self_echo":
        value["pubkey"] = SELF
    await emit(adapter, value, target)
    no_effects(adapter)
    assert not adapter._peer_budget_path().exists()
    if case == "dm_metadata":
        assert adapter._channel_state[CHANNEL]["chat_type"] == "group"


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [[], [HUMAN]])
async def test_peer_requires_ordinary_explicit_allowlist_even_if_core_allows_all(allowed):
    adapter = make_adapter({"allowed_users": allowed, "allow_all_users": True,
                            "reaction_only_users": [PEER]})
    await emit(adapter, event("denied"))
    no_effects(adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [None, False, "true", 1, RuntimeError("unavailable")])
async def test_authoritative_callback_must_return_literal_true(answer):
    adapter = make_adapter()
    callback = Mock(side_effect=answer) if isinstance(answer, Exception) else Mock(return_value=answer)
    adapter.set_authorization_check(callback if answer is not None else None)
    await emit(adapter, event("denied"))
    no_effects(adapter)
    assert not adapter._peer_budget_path().exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [
    "/approve session @Receiver", "@Receiver /approve session", "@Receiver /deny",
    "@Receiver @Receiver /model other", "@Other @Receiver /stop",
    "@Receiver: @Other, /restart", "@Receiver\n@Other\n/approve session",
    "@Other Agent @Receiver /approve", "@Other Agent\n@Receiver /approve",
    f"{SELF} @{buzz.hex_to_npub(SELF)} @Other /update", "@Receiver /",
])
async def test_peer_commands_are_rejected_after_all_leading_mentions(content):
    adapter = make_adapter()
    await emit(adapter, event("command", content=content))
    no_effects(adapter)
    assert not adapter._peer_budget_path().exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [
    {"peer_users": PEER}, {"peer_users": [PEER, "bad-key"]}, {"peer_users": None},
    {"peer_users": ["Receiver"]}, {"peer_users": {PEER: True}},
    {"peer_channels": []}, {"peer_channels": CHANNEL}, {"peer_channels": ["*"]},
    {"peer_channels": [""]}, {"peer_channels": [None]},
    {"peer_max_turns": 0}, {"peer_max_turns": -1}, {"peer_max_turns": 11},
    {"peer_max_turns": True}, {"peer_max_turns": 1.5}, {"peer_max_turns": "3"},
])
async def test_invalid_policy_never_downgrades_peer_to_human(extra):
    adapter = make_adapter(extra)
    await emit(adapter, event("peer", content="@Receiver /approve session"))
    await emit(adapter, event("peer-prompt"))
    no_effects(adapter)
    assert not adapter._peer_config_valid


@pytest.mark.asyncio
async def test_budget_shared_by_peers_and_threads_but_separate_per_channel():
    adapter = make_adapter({"peer_users": [PEER, OTHER], "allowed_users": [PEER, OTHER, HUMAN],
                            "peer_channels": [CHANNEL, SECOND], "peer_max_turns": 2})
    await emit(adapter, event("one"))
    await emit(adapter, event("two", pubkey=OTHER, tags=[["p", SELF], ["e", "thread-2", "", "root"]]))
    await emit(adapter, event("exhausted", timestamp=9000000000))
    assert adapter._dispatch_message.await_count == 2
    assert budget(adapter) == 0
    await emit(adapter, event("other-channel", channel=SECOND), SECOND)
    assert adapter._dispatch_message.await_count == 3
    assert budget(adapter, SECOND) == 1
    assert budget(adapter) == 0


@pytest.mark.asyncio
async def test_budget_is_persisted_before_profile_media_dispatch_or_reaction():
    adapter = make_adapter({"peer_max_turns": 1})
    value = event("attachment")
    value["tags"].append(["imeta", "url https://synthetic.relay.invalid/file.png",
                           "x " + "e" * 64, "size 1", "filename file.png", "m image/png"])

    async def media_check(_items):
        assert budget(adapter) == 0
        return []

    async def name_check(_pubkey):
        assert budget(adapter) == 0
        return "Synthetic peer"

    adapter._cache_inbound_attachments.side_effect = media_check
    adapter._resolve_user_name.side_effect = name_check
    await emit(adapter, value)
    adapter._cache_inbound_attachments.assert_awaited_once()
    adapter._resolve_user_name.assert_awaited_once()
    assert adapter._dispatch_message.await_count == 1
    for mock in (adapter._cache_inbound_attachments, adapter._resolve_user_name, adapter._dispatch_message):
        mock.reset_mock()
    await emit(adapter, event("exhausted-media", tags=value["tags"]))
    no_effects(adapter)


@pytest.mark.asyncio
async def test_restart_reconnect_and_elapsed_time_do_not_replenish(monkeypatch):
    adapter = make_adapter({"peer_max_turns": 1})
    await emit(adapter, event("one"))
    adapter._save_cursors()
    await adapter.disconnect()
    adapter._load_cursors()
    assert adapter._restore_channel_state(CHANNEL, "group")
    await emit(adapter, event("reconnect"))
    assert adapter._dispatch_message.await_count == 1
    monkeypatch.setattr(buzz.time, "time", lambda: 99999999)
    restarted = make_adapter({"peer_max_turns": 1})
    restarted._load_cursors()
    assert restarted._restore_channel_state(CHANNEL, "group")
    await emit(restarted, event("process-restart", timestamp=99999999))
    no_effects(restarted)
    assert budget(restarted) == 0


@pytest.mark.asyncio
async def test_fresh_authorized_addressed_human_resets_only_its_channel():
    adapter = make_adapter({"peer_channels": [CHANNEL, SECOND], "peer_max_turns": 1})
    await emit(adapter, event("spent"))
    await emit(adapter, event("spent-second"), SECOND)
    await emit(adapter, event("human", pubkey=HUMAN, timestamp=1002))
    assert budget(adapter) == 1
    assert budget(adapter, SECOND) == 0
    await emit(adapter, event("after-reset", timestamp=1003))
    assert budget(adapter) == 0
    assert adapter._dispatch_message.await_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["unauthorized", "callback_denied", "callback_absent", "callback_truthy",
                                   "unaddressed", "reaction", "bot", "bot_tag", "auth_tag",
                                   "agent_type", "reaction_only", "self", "dm", "old_human"])
async def test_non_human_or_unqualified_events_cannot_reset(case):
    adapter = make_adapter({"peer_max_turns": 1, "require_mention": False})
    await emit(adapter, event("spent"))
    value = event(case, pubkey=HUMAN, timestamp=1002)
    if case == "unauthorized":
        value["pubkey"] = OTHER
    elif case.startswith("callback_"):
        adapter.set_authorization_check({"callback_denied": lambda *_: False,
                                         "callback_absent": None,
                                         "callback_truthy": lambda *_: "yes"}[case])
    elif case == "unaddressed":
        value.update(content="general channel chatter", tags=[])
    elif case == "reaction":
        value["kind"] = 7
    elif case == "bot":
        value["is_bot"] = True
    elif case in {"bot_tag", "auth_tag"}:
        value["tags"].append([case.split("_")[0], HUMAN])
    elif case == "agent_type":
        value["agent_type"] = "native"
    elif case == "reaction_only":
        adapter._reaction_only_pubkeys.add(HUMAN)
    elif case == "self":
        value["pubkey"] = SELF
    elif case == "dm":
        adapter._channel_state[CHANNEL]["chat_type"] = "dm"
    elif case == "old_human":
        value["created_at"] = 999
    before = adapter._peer_budget_path().read_bytes()
    await emit(adapter, value)
    assert adapter._peer_budget_path().read_bytes() == before
    assert budget(adapter) == 0


@pytest.mark.asyncio
async def test_duplicates_and_replays_never_reset_even_after_cursor_loss():
    adapter = make_adapter({"peer_max_turns": 1})
    await emit(adapter, event("spent"))
    human = event("fresh-human", pubkey=HUMAN, timestamp=1002)
    await emit(adapter, human)
    await emit(adapter, event("spent-again", timestamp=1002))
    await emit(adapter, human)  # ordinary dedupe
    assert budget(adapter) == 0
    # Seen eviction/lost cursor is independent from durable peer reset history.
    adapter._channel_state[CHANNEL] = adapter._new_channel_state("group")
    await emit(adapter, human)
    assert budget(adapter) == 0
    restarted = make_adapter({"peer_max_turns": 1})
    await emit(restarted, human)
    assert budget(restarted) == 0
    # Distinct fresh human events in the same second still qualify.
    await emit(restarted, event("same-second-fresh", pubkey=HUMAN, timestamp=1002))
    assert budget(restarted) == 1
    await emit(restarted, event("spent-third", timestamp=1003))
    await emit(restarted, event("newer-human", pubkey=HUMAN, timestamp=1004))
    await emit(restarted, event("spent-fourth", timestamp=1005))
    restarted._channel_state[CHANNEL] = restarted._new_channel_state("group")
    await emit(restarted, human)  # even after watermark IDs have rotated away
    assert budget(restarted) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["json", "schema", "scope", "missing_channel", "negative",
                                         "bool", "read_error", "removed", "duplicate_member"])
async def test_corrupt_or_unreadable_state_fails_closed(corruption, monkeypatch):
    adapter = make_adapter()
    adapter._load_peer_budgets()
    path = adapter._peer_budget_path()
    if corruption == "read_error":
        real_read = Path.read_text

        def fail_read(target, *args, **kwargs):
            if target == path:
                raise PermissionError("synthetic denial")
            return real_read(target, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fail_read)
    elif corruption == "removed":
        path.unlink()
    elif corruption == "duplicate_member":
        path.write_text(path.read_text().replace('"remaining": 3', '"remaining": 0, "remaining": 3'))
    elif corruption == "json":
        path.write_text("not JSON")
    else:
        data = json.loads(path.read_text())
        if corruption == "schema":
            data = []
        elif corruption == "scope":
            data["identity"] = OTHER
        elif corruption == "missing_channel":
            data["channels"] = {}
        elif corruption == "negative":
            data["channels"][CHANNEL]["remaining"] = -1
        elif corruption == "bool":
            data["channels"][CHANNEL]["remaining"] = True
        path.write_text(json.dumps(data))
    await emit(adapter, event("peer"))
    no_effects(adapter)
    assert adapter._peer_budget_failed
    # Human traffic cannot heal corruption into a new grant.
    await emit(adapter, event("human", pubkey=HUMAN, timestamp=1002))
    adapter._dispatch_message.reset_mock()
    adapter._resolve_user_name.reset_mock()
    await emit(adapter, event("peer-after-human", timestamp=1003))
    no_effects(adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["initial", "consume", "human_reset"])
async def test_persistence_failure_never_releases_peer_side_effects(phase, monkeypatch):
    import utils

    adapter = make_adapter({"peer_max_turns": 1})
    if phase != "initial":
        adapter._load_peer_budgets()
    if phase == "human_reset":
        await emit(adapter, event("spent"))
    monkeypatch.setattr(utils, "atomic_json_write", Mock(side_effect=OSError("disk full")))
    if phase == "human_reset":
        await emit(adapter, event("human", pubkey=HUMAN, timestamp=1002))
    for mock in (adapter._dispatch_message, adapter._resolve_user_name):
        mock.reset_mock()
    await emit(adapter, event("peer", timestamp=1003))
    no_effects(adapter)
    assert adapter._peer_budget_failed


@pytest.mark.asyncio
async def test_concurrent_events_cannot_overspend_before_first_await():
    adapter = make_adapter({"peer_max_turns": 1})
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_lookup(_pubkey):
        assert budget(adapter) == 0
        entered.set()
        await release.wait()
        return "Synthetic sender"

    adapter._resolve_user_name.side_effect = delayed_lookup
    first = asyncio.create_task(emit(adapter, event("first")))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await emit(adapter, event("racer"))
        assert adapter._resolve_user_name.await_count == 1
    finally:
        release.set()
        await asyncio.wait_for(first, 2)
    assert adapter._dispatch_message.await_count == 1


@pytest.mark.asyncio
async def test_production_dispatch_retains_provenance_and_core_auth_uses_ordinary_allowlist(monkeypatch):
    from gateway.config import GatewayConfig, Platform
    from gateway.platform_registry import PlatformEntry, platform_registry
    from gateway.run import GatewayRunner
    from gateway.session import SessionSource

    adapter = make_adapter({"allowed_users": [HUMAN, buzz.hex_to_npub(PEER)]})
    platform = Platform("buzz")
    platform_registry.register(PlatformEntry(
        name="buzz", label="Buzz", adapter_factory=lambda _: None, check_fn=lambda: True,
        allowed_users_env="BUZZ_ALLOWED_USERS", allow_all_env="BUZZ_ALLOW_ALL_USERS",
    ))
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig()
    runner.pairing_store = None
    runner.adapters = {platform: adapter}
    adapter.set_authorization_check(lambda user, chat_type, chat_id: runner._is_user_authorized(
        SessionSource(platform=platform, user_id=user, chat_type=chat_type, chat_id=chat_id)
    ))
    adapter._message_handler = AsyncMock()
    adapter.handle_message = AsyncMock()
    del adapter._dispatch_message  # Exercise the actual MessageEvent construction.
    try:
        await emit(adapter, event("real-dispatch"))
        dispatched = adapter.handle_message.call_args.args[0]
        assert dispatched.text.startswith("[Untrusted agent collaboration")
        assert not dispatched.is_command()
        assert dispatched.source.user_id == PEER
        assert runner._is_user_authorized(dispatched.source) is True
        monkeypatch.setenv("BUZZ_ALLOWED_USERS", HUMAN)
        await emit(adapter, event("core-denial"))
        assert adapter.handle_message.await_count == 1
        assert budget(adapter) == 2
        assert runner._is_user_authorized(dispatched.source) is False
    finally:
        platform_registry.unregister("buzz")


@pytest.mark.asyncio
async def test_budget_namespace_binds_profile_relay_and_self_identity(monkeypatch, tmp_path):
    adapter = make_adapter({"peer_max_turns": 1})
    await emit(adapter, event("spent"))
    original = adapter._peer_budget_path()
    other_relay = make_adapter({"relay_url": "https://other.invalid", "peer_max_turns": 1})
    other_identity = make_adapter({"peer_max_turns": 1})
    other_identity._self_pubkey = OTHER
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "second-profile"))
    other_profile = make_adapter({"peer_max_turns": 1})
    assert adapter._peer_budget_path() == original  # ambient scope doesn't move it
    assert len({a._peer_budget_path() for a in (adapter, other_relay, other_identity, other_profile)}) == 4
    for other in (other_relay, other_identity, other_profile):
        assert other._load_peer_budgets()["channels"][CHANNEL]["remaining"] == 1
    assert budget(adapter) == 0


@pytest.mark.asyncio
async def test_real_new_process_loads_exhausted_budget_without_credentials():
    import os
    import subprocess
    import sys

    adapter = make_adapter({"peer_max_turns": 1})
    await emit(adapter, event("spent"))
    child = subprocess.run([
        sys.executable, "-c",
        "import asyncio, json; "
        "from tests.gateway.test_buzz_peer_collaboration import make_adapter, emit, event, budget; "
        "a = make_adapter({'peer_max_turns': 1}); "
        "asyncio.run(emit(a, event('new-process'))); "
        "print(json.dumps([a._dispatch_message.await_count, budget(a)]))",
    ], env={key: os.environ[key] for key in (
        "HOME", "HERMES_HOME", "PATH", "TMPDIR", "PYTHONDONTWRITEBYTECODE",
    ) if key in os.environ}, capture_output=True, text=True, timeout=20)
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout) == [0, 0]


@pytest.mark.asyncio
async def test_websocket_reconnect_does_not_rearm_peer_budget(monkeypatch):
    import websockets

    adapter = make_adapter({"peer_max_turns": 1})
    adapter._authenticate_websocket = AsyncMock()
    connections = []
    replay_checked = asyncio.Event()

    class Socket:
        def __init__(self, index):
            self.index = index
            self.delivered = False
            self.exited = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            self.exited = True

        async def send(self, _):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.delivered:
                self.delivered = True
                return json.dumps(["EVENT", "hermes-buzz-0", event(f"connection-{self.index}")])
            if self.index == 0:
                raise StopAsyncIteration
            replay_checked.set()
            await asyncio.Event().wait()

    def connect(*_, **__):
        socket = Socket(len(connections))
        connections.append(socket)
        return socket

    monkeypatch.setattr(websockets, "connect", connect)
    adapter._ws_task = asyncio.create_task(adapter._websocket_loop())
    try:
        await asyncio.wait_for(replay_checked.wait(), 2)
        assert len(connections) == 2 and connections[0].exited
        assert adapter._dispatch_message.await_count == 1
        assert budget(adapter) == 0
    finally:
        await asyncio.wait_for(adapter.disconnect(), 2)
    assert all(s.exited for s in connections)


@pytest.mark.asyncio
async def test_peer_policy_edits_never_refill_existing_grant():
    adapter = make_adapter({"peer_max_turns": 1})
    await emit(adapter, event("spent"))
    larger = make_adapter({"peer_max_turns": 10})
    await emit(larger, event("larger-bound"))
    no_effects(larger)
    changed_channels = make_adapter({"peer_channels": [CHANNEL, SECOND]})
    await emit(changed_channels, event("changed-channel-set"))
    no_effects(changed_channels)
    assert changed_channels._peer_budget_failed
    assert budget(adapter) == 0


@pytest.mark.asyncio
async def test_reset_watermark_same_second_capacity_does_not_rotate_or_rearm():
    adapter = make_adapter({"peer_max_turns": 1})
    data = adapter._load_peer_budgets()
    data["channels"][CHANNEL].update(remaining=0, human_ts=1002,
                                    human_ids=[str(i) for i in range(buzz._SEEN_CAP)])
    assert adapter._save_peer_budgets(data)
    await emit(adapter, event("over-cap-human", pubkey=HUMAN, timestamp=1002))
    assert budget(adapter) == 0
    await emit(adapter, event("new-second-human", pubkey=HUMAN, timestamp=1003))
    assert budget(adapter) == 1
