from __future__ import annotations

from authorizer.handler import handler


def _event(cookie: str | None) -> dict:
    return {"cookies": [cookie] if cookie else []}


def test_mints_new_session_when_no_cookie(tables):
    result = handler(_event(None), None)
    assert result["isAuthorized"] is True
    assert result["context"]["is_new_session"] == "true"
    session_id = result["context"]["session_id"]

    item = tables.Table("Sessions").get_item(Key={"session_id": session_id})["Item"]
    assert item["request_count"] == 1


def test_reuses_valid_existing_session_and_increments_request_count(tables):
    first = handler(_event(None), None)
    session_id = first["context"]["session_id"]

    second = handler(_event(f"session_id={session_id}"), None)
    assert second["isAuthorized"] is True
    assert second["context"]["is_new_session"] == "false"
    assert second["context"]["session_id"] == session_id

    item = tables.Table("Sessions").get_item(Key={"session_id": session_id})["Item"]
    assert item["request_count"] == 2


def test_rejects_malformed_session_cookie(tables):
    result = handler(_event("session_id=not-a-uuid"), None)
    assert result == {"isAuthorized": False}
