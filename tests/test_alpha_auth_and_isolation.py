"""Unit and integration tests for Alpha Test Authentication and Data Isolation.

Verifies:
1. Authentication:
   - Login with valid/invalid credentials
   - Session cookie creation and verification
   - X-User-Id header fallback
   - Current user introspection (/api/auth/me) and logout
2. Chat Isolation:
   - User A cannot see User B's chats in /api/chats
   - User A cannot read, modify, or delete User B's chats (403 Forbidden)
   - Admin can view all chats
3. Document Isolation & Deduplication:
   - Registry deduplication is user-scoped (User B is not blocked from uploading a file User A uploaded)
   - User A cannot see User B's documents in /api/documents
   - User A cannot delete User B's document (403 Forbidden)
4. Vector Store Qdrant Filtering:
   - _build_filter correctly constructs MatchAny([target_user, "system", "shared"]) + IsEmptyCondition
   - Chunks belonging to other users are excluded
"""

from __future__ import annotations

import pytest
from pathlib import Path
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch

from src.main import app
from src.core.state import state_manager
from src.core.ingestion_registry import IngestionRegistry, RegistryStatus
from src.stages.s11_vector_store import QdrantStore
from qdrant_client.models import IsEmptyCondition


@pytest.fixture
def clean_state(tmp_path):
    """Isolate state manager with a clean temp directory."""
    original_chats_file = state_manager.chats_file
    original_messages_file = state_manager.messages_file
    original_documents_file = state_manager.documents_file

    state_manager.chats_file = tmp_path / "chats.json"
    state_manager.messages_file = tmp_path / "messages.json"
    state_manager.documents_file = tmp_path / "documents.json"

    yield state_manager

    state_manager.chats_file = original_chats_file
    state_manager.messages_file = original_messages_file
    state_manager.documents_file = original_documents_file


# ---------------------------------------------------------------------------
# 1. Authentication Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auth_login_success():
    """Verify login with valid alpha credentials returns 200 and sets session cookie."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/auth/login",
            json={"username": "mihir", "password": "alpha_pass_1"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "logged_in"
        assert data["user_id"] == "mihir"
        assert "alpha_session" in res.cookies


@pytest.mark.asyncio
async def test_auth_login_invalid_password():
    """Verify login with invalid password returns 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/auth/login",
            json={"username": "mihir", "password": "wrong_password"},
        )
        assert res.status_code == 401
        assert "Invalid Alpha credentials" in res.json()["detail"]


@pytest.mark.asyncio
async def test_auth_login_unknown_user():
    """Verify login with unknown username returns 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/auth/login",
            json={"username": "ghost_user", "password": "password"},
        )
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_auth_me_cookie_and_header():
    """Verify /api/auth/me works with cookie, header, and falls back to anonymous."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Anonymous (no auth)
        res_anon = await client.get("/api/auth/me")
        assert res_anon.status_code == 200
        assert res_anon.json()["user_id"] == "anonymous"
        assert res_anon.json()["authenticated"] is False

        # Header fallback (X-User-Id)
        res_header = await client.get(
            "/api/auth/me",
            headers={"X-User-Id": "rahul"},
        )
        assert res_header.status_code == 200
        assert res_header.json()["user_id"] == "rahul"
        assert res_header.json()["authenticated"] is True

        # Cookie authentication
        login_res = await client.post(
            "/api/auth/login",
            json={"username": "priya", "password": "alpha_pass_3"},
        )
        assert login_res.status_code == 200
        res_cookie = await client.get("/api/auth/me")
        assert res_cookie.status_code == 200
        assert res_cookie.json()["user_id"] == "priya"
        assert res_cookie.json()["authenticated"] is True

        # Logout clears cookie
        logout_res = await client.post("/api/auth/logout")
        assert logout_res.status_code == 200
        res_post_logout = await client.get("/api/auth/me")
        assert res_post_logout.json()["user_id"] == "anonymous"


# ---------------------------------------------------------------------------
# 2. Chat Isolation Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_isolation_between_users(clean_state):
    """Verify User A's chats cannot be viewed, edited, or deleted by User B."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Mihir creates a chat
        res_m = await client.post(
            "/api/chats",
            json={"title": "Mihir Confidential Plan"},
            headers={"X-User-Id": "mihir"},
        )
        assert res_m.status_code == 200
        mihir_chat = res_m.json()
        mihir_chat_id = mihir_chat["id"]
        assert mihir_chat["userId"] == "mihir"

        # 2. Rahul creates a chat
        res_r = await client.post(
            "/api/chats",
            json={"title": "Rahul Public Notes"},
            headers={"X-User-Id": "rahul"},
        )
        assert res_r.status_code == 200
        rahul_chat = res_r.json()
        rahul_chat_id = rahul_chat["id"]

        # 3. Mihir lists chats -> sees only Mihir's chat
        res_mihir_list = await client.get("/api/chats", headers={"X-User-Id": "mihir"})
        assert res_mihir_list.status_code == 200
        mihir_chats = res_mihir_list.json()
        assert any(c["id"] == mihir_chat_id for c in mihir_chats)
        assert not any(c["id"] == rahul_chat_id for c in mihir_chats)

        # 4. Rahul lists chats -> sees only Rahul's chat
        res_rahul_list = await client.get("/api/chats", headers={"X-User-Id": "rahul"})
        assert res_rahul_list.status_code == 200
        rahul_chats = res_rahul_list.json()
        assert any(c["id"] == rahul_chat_id for c in rahul_chats)
        assert not any(c["id"] == mihir_chat_id for c in rahul_chats)

        # 5. Rahul attempts to read Mihir's messages -> 403 Forbidden
        res_read = await client.get(
            f"/api/chats/{mihir_chat_id}/messages",
            headers={"X-User-Id": "rahul"},
        )
        assert res_read.status_code == 403
        assert "Access denied" in res_read.json()["detail"]

        # 6. Rahul attempts to update Mihir's chat title -> 403 Forbidden
        res_patch = await client.patch(
            f"/api/chats/{mihir_chat_id}",
            json={"title": "Hacked Title"},
            headers={"X-User-Id": "rahul"},
        )
        assert res_patch.status_code == 403

        # 7. Rahul attempts to delete Mihir's chat -> 403 Forbidden
        res_del = await client.delete(
            f"/api/chats/{mihir_chat_id}",
            headers={"X-User-Id": "rahul"},
        )
        assert res_del.status_code == 403

        # 8. Admin lists chats -> can see all chats
        res_admin_list = await client.get("/api/chats", headers={"X-User-Id": "admin"})
        assert res_admin_list.status_code == 200
        admin_chats = res_admin_list.json()
        assert any(c["id"] == mihir_chat_id for c in admin_chats)
        assert any(c["id"] == rahul_chat_id for c in admin_chats)


# ---------------------------------------------------------------------------
# 3. Document Registry & Ingestion Isolation Tests
# ---------------------------------------------------------------------------

def test_ingestion_registry_user_deduplication(tmp_path):
    """Verify deduplication is user-scoped in IngestionRegistry."""
    registry_file = tmp_path / "test_registry.json"
    registry = IngestionRegistry(registry_path=registry_file)

    dummy_file = tmp_path / "sample_doc.txt"
    dummy_file.write_text("Unique content for alpha testing isolation 2026")

    # 1. Mihir checks file -> NEW_FILE
    check_m1 = registry.check(dummy_file, user_id="mihir")
    assert check_m1.status == RegistryStatus.NEW_FILE

    # 2. Mihir creates version
    entry_m = registry.create_version(
        file_path=dummy_file,
        content_hash=check_m1.sha256,
        total_chunks=5,
        user_id="mihir",
    )
    assert entry_m["user_id"] == "mihir"

    # 3. Mihir checks same file again -> ALREADY_INGESTED
    check_m2 = registry.check(dummy_file, user_id="mihir")
    assert check_m2.status == RegistryStatus.ALREADY_INGESTED

    # 4. Rahul checks the EXACT SAME file -> NEW_FILE (not blocked by Mihir's upload!)
    check_r1 = registry.check(dummy_file, user_id="rahul")
    assert check_r1.status == RegistryStatus.NEW_FILE

    # 5. Rahul creates his version
    entry_r = registry.create_version(
        file_path=dummy_file,
        content_hash=check_r1.sha256,
        total_chunks=5,
        user_id="rahul",
    )
    assert entry_r["user_id"] == "rahul"

    # 6. Active listing isolation
    mihir_docs = registry.get_active(user_id="mihir")
    rahul_docs = registry.get_active(user_id="rahul")

    assert any(d["document_id"] == entry_m["document_id"] for d in mihir_docs)
    assert not any(d["document_id"] == entry_r["document_id"] for d in mihir_docs)

    assert any(d["document_id"] == entry_r["document_id"] for d in rahul_docs)
    assert not any(d["document_id"] == entry_m["document_id"] for d in rahul_docs)


@pytest.mark.asyncio
async def test_ui_document_endpoints_isolation(tmp_path):
    """Verify /api/documents respects user ownership and blocks unauthorized deletion."""
    registry_file = tmp_path / "test_reg_ui.json"
    dummy_file_m = tmp_path / "mihir_strategy.pdf"
    dummy_file_m.write_text("Mihir Strategy Document")

    dummy_file_r = tmp_path / "rahul_code.py"
    dummy_file_r.write_text("Rahul Code Snippets")

    test_registry = IngestionRegistry(registry_path=registry_file)
    v_m = test_registry.create_version(dummy_file_m, "hash_m", 10, user_id="mihir")
    v_r = test_registry.create_version(dummy_file_r, "hash_r", 8, user_id="rahul")

    with patch("src.core.ingestion_registry.IngestionRegistry.get_all", return_value=test_registry.get_all()), \
         patch("src.core.ingestion_registry.IngestionRegistry.get_by_document_id", side_effect=test_registry.get_by_document_id):

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Mihir lists docs -> sees only Mihir's doc
            res_m = await client.get("/api/documents", headers={"X-User-Id": "mihir"})
            assert res_m.status_code == 200
            m_names = [d["name"] for d in res_m.json()]
            assert "mihir_strategy.pdf" in m_names
            assert "rahul_code.py" not in m_names

            # Rahul lists docs -> sees only Rahul's doc
            res_r = await client.get("/api/documents", headers={"X-User-Id": "rahul"})
            assert res_r.status_code == 200
            r_names = [d["name"] for d in res_r.json()]
            assert "rahul_code.py" in r_names
            assert "mihir_strategy.pdf" not in r_names

            # Rahul attempts to delete Mihir's doc -> 403 Forbidden
            res_del = await client.delete(
                f"/api/documents/{v_m['document_id']}",
                headers={"X-User-Id": "rahul"},
            )
            assert res_del.status_code == 403
            assert "Access denied" in res_del.json()["detail"]


# ---------------------------------------------------------------------------
# 4. Qdrant Vector Store Filter Tests
# ---------------------------------------------------------------------------

def test_qdrant_store_build_filter_user_isolation():
    """Verify QdrantStore._build_filter constructs correct multi-tenant filters."""
    # When user_id="mihir" is passed
    q_filter = QdrantStore._build_filter({"user_id": "mihir"})
    assert q_filter is not None
    assert q_filter.must is not None

    # Find the user clause
    user_clause = next((cond for cond in q_filter.must if hasattr(cond, "should") and cond.should), None)
    assert user_clause is not None
    should_conditions = user_clause.should

    # Verify MatchAny condition has target user, system, and shared
    match_any_cond = next((c for c in should_conditions if hasattr(c, "match") and hasattr(c.match, "any")), None)
    assert match_any_cond is not None
    assert "mihir" in match_any_cond.match.any
    assert "system" in match_any_cond.match.any
    assert "shared" in match_any_cond.match.any
    assert "rahul" not in match_any_cond.match.any

    # Verify IsEmptyCondition is included for legacy unassigned chunks
    empty_cond = next((c for c in should_conditions if isinstance(c, IsEmptyCondition)), None)
    assert empty_cond is not None
    assert empty_cond.is_empty.key == "user_id"

    # Always excludes inactive (superseded) chunks
    assert any(c.key == "active" for c in q_filter.must_not)
