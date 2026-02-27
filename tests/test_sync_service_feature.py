import asyncio

from backend.sync import service


def test_get_sync_public_status_masks_secret(monkeypatch):
    fake_cfg = {
        "sync": {
            "enabled": True,
            "provider": "s3",
            "endpoint_url": "https://example.com",
            "bucket": "bucket-a",
            "region": "auto",
            "access_key_id": "AKIA123456",
            "secret_access_key": "super-secret-value",
            "object_prefix": "mnesis",
            "device_id": "device-1",
            "auto_sync": False,
            "auto_sync_interval_minutes": 60,
        },
        "sync_status": {
            "last_sync_at": None,
            "last_sync_size_bytes": 0,
            "last_sync_result": "never",
            "devices": [],
            "last_error": None,
        },
    }

    monkeypatch.setattr(service, "load_config", lambda force_reload=False: fake_cfg)
    service.lock_sync()

    status = service.get_sync_public_status()
    assert status["sync"]["secret_access_key"].startswith("su")
    assert "*" in status["sync"]["secret_access_key"]
    assert status["unlocked"] is False


def test_update_sync_config_preserves_masked_secret_and_normalizes(monkeypatch):
    state = {
        "sync": {
            "enabled": True,
            "provider": "s3",
            "endpoint_url": "https://example.com",
            "force_path_style": False,
            "bucket": "bucket-a",
            "region": "auto",
            "access_key_id": "AKIAORIGINAL",
            "secret_access_key": "very-secret",
            "object_prefix": "mnesis",
            "device_id": "device-1",
            "auto_sync": True,
            "auto_sync_interval_minutes": 60,
        },
        "sync_status": {
            "last_sync_at": None,
            "last_sync_size_bytes": 0,
            "last_sync_result": "never",
            "devices": [],
            "last_error": None,
        },
    }

    def _load_config(force_reload=False):
        return state

    def _save_config(new_cfg):
        state.clear()
        state.update(new_cfg)

    monkeypatch.setattr(service, "load_config", _load_config)
    monkeypatch.setattr(service, "save_config", _save_config)
    monkeypatch.setattr(service, "get_sync_public_status", lambda: {"sync": state["sync"], "sync_status": state["sync_status"], "unlocked": False})

    service.update_sync_config(
        {
            "secret_access_key": "********",
            "access_key_id": "********",
            "auto_sync_interval_minutes": 1,
            "device_id": "",
            "provider": "CUSTOM",
            "force_path_style": True,
            "endpoint_url": "  https://r2.example.com  ",
        }
    )

    assert state["sync"]["secret_access_key"] == "very-secret"
    assert state["sync"]["access_key_id"] == "AKIAORIGINAL"
    assert state["sync"]["provider"] == "custom"
    assert state["sync"]["force_path_style"] is True
    assert state["sync"]["auto_sync_interval_minutes"] == 5
    assert state["sync"]["device_id"]
    assert state["sync"]["endpoint_url"] == "https://r2.example.com"


def test_update_sync_config_preserves_pretty_masked_secret(monkeypatch):
    state = {
        "sync": {
            "enabled": True,
            "provider": "s3",
            "endpoint_url": "https://example.com",
            "force_path_style": False,
            "bucket": "bucket-a",
            "region": "auto",
            "access_key_id": "AKIAORIGINAL",
            "secret_access_key": "very-secret",
            "webdav_password": "",
            "object_prefix": "mnesis",
            "device_id": "device-1",
            "auto_sync": True,
            "auto_sync_interval_minutes": 60,
        },
        "sync_status": {
            "last_sync_at": None,
            "last_sync_size_bytes": 0,
            "last_sync_result": "never",
            "devices": [],
            "last_error": None,
        },
    }

    def _load_config(force_reload=False):
        return state

    def _save_config(new_cfg):
        state.clear()
        state.update(new_cfg)

    monkeypatch.setattr(service, "load_config", _load_config)
    monkeypatch.setattr(service, "save_config", _save_config)
    monkeypatch.setattr(service, "get_sync_public_status", lambda: {"sync": state["sync"], "sync_status": state["sync_status"], "unlocked": False})

    masked_secret = service._masked(state["sync"]["secret_access_key"])
    service.update_sync_config({"secret_access_key": masked_secret})
    assert state["sync"]["secret_access_key"] == "very-secret"


def test_ensure_sync_ready_for_s3_does_not_require_endpoint():
    service._ensure_sync_ready(
        {
            "provider": "s3",
            "bucket": "bucket-a",
            "access_key_id": "AKIA123",
            "secret_access_key": "SECRET123",
            "endpoint_url": "",
        }
    )


def test_ensure_sync_ready_for_custom_requires_endpoint():
    try:
        service._ensure_sync_ready(
            {
                "provider": "custom",
                "bucket": "bucket-a",
                "access_key_id": "AKIA123",
                "secret_access_key": "SECRET123",
                "endpoint_url": "",
            }
        )
    except ValueError as exc:
        assert "endpoint_url" in str(exc)
    else:
        raise AssertionError("Expected ValueError when endpoint_url is missing for custom provider")


def test_ensure_sync_ready_for_webdav_requires_credentials():
    try:
        service._ensure_sync_ready(
            {
                "provider": "webdav",
                "webdav_url": "https://cloud.example.com/remote.php/dav/files/user",
                "webdav_username": "",
                "webdav_password": "",
            }
        )
    except ValueError as exc:
        msg = str(exc)
        assert "webdav_username" in msg
        assert "webdav_password" in msg
    else:
        raise AssertionError("Expected ValueError when WebDAV credentials are missing")


def test_lock_unlock_cycle(monkeypatch):
    monkeypatch.setattr(service, "derive_key_from_passphrase", lambda passphrase: b"x" * 32)

    service.lock_sync()
    assert service.is_sync_unlocked() is False

    service.unlock_sync("this-is-a-valid-passphrase")
    assert service.is_sync_unlocked() is True

    service.lock_sync()
    assert service.is_sync_unlocked() is False


def test_run_sync_now_uploads_encrypted_snapshot(monkeypatch):
    cfg = {
        "sync": {
            "enabled": True,
            "provider": "s3",
            "endpoint_url": "https://r2.example.com",
            "bucket": "bucket-a",
            "region": "auto",
            "access_key_id": "AKIA123",
            "secret_access_key": "SECRET123",
            "object_prefix": "mnesis",
            "device_id": "device-1",
            "auto_sync": False,
            "auto_sync_interval_minutes": 60,
        },
        "sync_status": {
            "last_sync_at": None,
            "last_sync_size_bytes": 0,
            "last_sync_result": "never",
            "devices": [],
            "last_error": None,
        },
    }

    updates = {}

    monkeypatch.setattr(service, "load_config", lambda force_reload=False: cfg)
    monkeypatch.setattr(service, "download_latest_encrypted_snapshot", lambda sync_cfg: None)
    monkeypatch.setattr(
        service,
        "_build_plain_snapshot_zip",
        lambda: (
            b"plain-snapshot",
            {
                "checksum_plain_sha256": "abc123",
                "size_bytes": 14,
                "tables": {},
            },
        ),
    )
    monkeypatch.setattr(
        service,
        "encrypt_snapshot",
        lambda plaintext, key, metadata=None: {
            "version": 1,
            "checksum_sha256": "enc123",
            "nonce_b64": "AA==",
            "ciphertext_b64": "AA==",
        },
    )
    monkeypatch.setattr(
        service,
        "upload_encrypted_snapshot",
        lambda sync_cfg, snapshot_document, key_name: {
            "snapshot_key": f"mnesis/snapshots/{key_name}.json",
            "latest_key": "mnesis/latest.json",
            "size_bytes": 321,
        },
    )
    monkeypatch.setattr(
        service,
        "_update_sync_status",
        lambda success, payload=None, error=None: updates.update({"success": success, "payload": payload, "error": error}),
    )

    service._UNLOCKED_SYNC_KEY = b"x" * 32
    report = asyncio.run(service.run_sync_now(source="manual"))

    assert report["status"] == "ok"
    assert report["uploaded"]["latest_key"] == "mnesis/latest.json"
    assert updates["success"] is True
