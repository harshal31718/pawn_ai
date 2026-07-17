"""Project CRUD + two-way chat moves (Phase M — memory scoping, M.5).

Storage: Google Drive only, mirroring conversations.py's pattern (no
local-filesystem fallback — see core/drive_factory.py). Postgres's
memory_chunks.scope_type/scope_id are kept in sync on every move, but Drive
folder placement is always the authoritative source of truth — a failure
partway through a move is recoverable via memory.indexer.rebuild_index.
"""

from contextlib import AsyncExitStack

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.core.drive_factory import call_drive, require_drive_for_user
from app.db.postgres_client import execute
from app.memory import indexer
from app.memory.locks import get_conv_lock
from app.storage import conversations_drive, projects_drive

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    id: str | None = None              # client-owned project id (optimistic UI)
    name: str = "New Project"
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


# ─── Blocking storage helpers (run via run_in_threadpool so Drive/Postgres
#     I/O never executes on the event loop) ────────────────────────────────


def _create(drive, project_id, name, description):
    return projects_drive.create_project(drive, project_id=project_id, name=name, description=description)


def _list(drive):
    projects = projects_drive.list_projects(drive)
    for p in projects:
        p["chat_count"] = len(projects_drive.list_project_chats(drive, p["id"]))
    return projects


def _update(drive, project_id, name, description):
    return projects_drive.update_project(drive, project_id, name=name, description=description)


def _delete(drive, project_id):
    if not projects_drive.get_project_meta(drive, project_id):
        return False
    projects_drive.delete_project(drive, project_id)
    return True


def _delete_project_chunks(user_id, project_id):
    execute(
        "delete from memory_chunks where user_id = %s and scope_type = 'project' and scope_id = %s",
        (user_id, project_id),
    )


def _move_in_drive(drive, conv_id, project_id):
    chats_folder = conversations_drive._chats_folder(drive)
    project_folder = projects_drive._project_folder(drive, project_id)
    projects_drive.move_chat(drive, conv_id, chats_folder, project_folder)


def _move_out_drive(drive, conv_id, project_id):
    project_folder = projects_drive._project_folder(drive, project_id)
    chats_folder = conversations_drive._chats_folder(drive)
    projects_drive.move_chat(drive, conv_id, project_folder, chats_folder)


def _update_chunk_scope(user_id, conv_id, scope_type, scope_id):
    execute(
        "update memory_chunks set scope_type = %s, scope_id = %s where user_id = %s and conv_id = %s",
        (scope_type, scope_id, user_id, conv_id),
    )


# ─── Routes ──────────────────────────────────────────────────────────────


@router.post("")
async def create_project(req: ProjectCreate, request: Request):
    user_id = request.state.user_id
    drive = await run_in_threadpool(require_drive_for_user, user_id)
    return await run_in_threadpool(call_drive, _create, drive, req.id, req.name, req.description)


@router.get("")
async def list_projects(request: Request):
    user_id = request.state.user_id
    drive = await run_in_threadpool(require_drive_for_user, user_id)
    return await run_in_threadpool(call_drive, _list, drive)


@router.patch("/{project_id}")
async def rename_project(project_id: str, req: ProjectUpdate, request: Request):
    """Renames the project, updates its description, or both — whichever
    fields are set on the request body (F-10)."""
    user_id = request.state.user_id
    drive = await run_in_threadpool(require_drive_for_user, user_id)
    updated = await run_in_threadpool(call_drive, _update, drive, project_id, req.name, req.description)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project {project_id} not found.")
    return updated


@router.delete("/{project_id}")
async def delete_project(project_id: str, request: Request):
    """Cascade: removes the project's Drive folder (every contained chat's
    meta/messages/summary/rag files included) and every Postgres row scoped
    to this project.

    Holds every contained chat's per-(user,conv) lock for the whole delete —
    same lock index_turn_task and the move endpoints use — so an in-flight
    indexing pass for one of these chats can't land an add_chunk() write
    after the Drive folder (and its scope) is already gone, which would
    otherwise orphan a Postgres row that rebuild_index can no longer repair
    (there's nothing left on Drive to rebuild it from)."""
    user_id = request.state.user_id
    drive = await run_in_threadpool(require_drive_for_user, user_id)

    project_meta = await run_in_threadpool(call_drive, projects_drive.get_project_meta, drive, project_id)
    if not project_meta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project {project_id} not found.")

    chat_metas = await run_in_threadpool(call_drive, projects_drive.list_project_chats, drive, project_id)
    conv_ids = [m["id"] for m in chat_metas]

    async with AsyncExitStack() as locks:
        for conv_id in conv_ids:
            await locks.enter_async_context(get_conv_lock(user_id, conv_id))

        ok = await run_in_threadpool(call_drive, _delete, drive, project_id)
        if not ok:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project {project_id} not found.")
        await run_in_threadpool(_delete_project_chunks, user_id, project_id)

    return {"status": "ok"}


@router.post("/{project_id}/chats/{conv_id}")
async def move_chat_in(project_id: str, conv_id: str, request: Request):
    """Move a standalone chat into a project. Idempotent: re-running while
    already inside this project is a no-op. Moving a chat that's already in
    a *different* project is rejected — use move-out then move-in."""
    user_id = request.state.user_id
    drive = await run_in_threadpool(require_drive_for_user, user_id)

    project_meta = await run_in_threadpool(call_drive, projects_drive.get_project_meta, drive, project_id)
    if not project_meta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project {project_id} not found.")

    current_scope = await run_in_threadpool(call_drive, conversations_drive.resolve_conv_scope, drive, conv_id)
    if current_scope is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Conversation {conv_id} not found.")
    if current_scope == ("project", project_id):
        return {"status": "ok"}
    if current_scope[0] == "project":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conversation {conv_id} is already in another project.",
        )

    # Drive is authoritative (moved first); the shared per-(user,conv) lock
    # keeps this atomic with respect to M.3's index_turn_task, so an
    # in-flight indexing pass either finishes under the old scope first or
    # sees the new one after — never interleaved.
    async with get_conv_lock(user_id, conv_id):
        await run_in_threadpool(call_drive, _move_in_drive, drive, conv_id, project_id)
        await run_in_threadpool(_update_chunk_scope, user_id, conv_id, "project", project_id)
        indexer.evict_scope(user_id, conv_id)

    return {"status": "ok"}


@router.delete("/{project_id}/chats/{conv_id}")
async def move_chat_out(project_id: str, conv_id: str, request: Request):
    """Move a chat back out of a project to standalone. Idempotent:
    re-running while already standalone is a no-op."""
    user_id = request.state.user_id
    drive = await run_in_threadpool(require_drive_for_user, user_id)

    current_scope = await run_in_threadpool(call_drive, conversations_drive.resolve_conv_scope, drive, conv_id)
    if current_scope is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Conversation {conv_id} not found.")
    if current_scope == ("chat", conv_id):
        return {"status": "ok"}
    if current_scope != ("project", project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conv_id} is not in project {project_id}.",
        )

    async with get_conv_lock(user_id, conv_id):
        await run_in_threadpool(call_drive, _move_out_drive, drive, conv_id, project_id)
        await run_in_threadpool(_update_chunk_scope, user_id, conv_id, "chat", conv_id)
        indexer.evict_scope(user_id, conv_id)

    return {"status": "ok"}
