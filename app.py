import asyncio
import json
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from typing import Any, Optional

import instaloader
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import os as _os  # alias so later "import os" if any doesn't collide

CODE_DIR = Path(_os.environ.get("FEEDSCRIPT_CODE_DIR", Path(__file__).parent)).resolve()
DATA_DIR = Path(_os.environ.get("FEEDSCRIPT_DATA_DIR", Path(__file__).parent)).resolve()
ROOT = DATA_DIR  # legacy alias used by run_transcribe_job for the default output base

SESSIONS_DIR = DATA_DIR / "sessions"
OUTPUT_DIR = DATA_DIR / "output"
STATIC_DIR = CODE_DIR / "static"
TEMPLATES_DIR = CODE_DIR / "templates"

for d in (SESSIONS_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

STATE_FILE = DATA_DIR / "state.json"
executor = ThreadPoolExecutor(max_workers=2)
_whisper_models: dict[str, Any] = {}
_jobs: dict[str, dict] = {}


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def human_sleep(min_s: float, max_s: float) -> None:
    time.sleep(random.uniform(min_s, max_s))


async def async_human_sleep(min_s: float, max_s: float) -> None:
    await asyncio.sleep(random.uniform(min_s, max_s))


def parse_cookies_blob(blob: str) -> dict:
    blob = blob.strip()
    if not blob:
        raise ValueError("Empty cookies")
    data = json.loads(blob)
    needed = {"sessionid", "ds_user_id", "csrftoken"}
    result: dict[str, str] = {}
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("Name")
                value = entry.get("value") or entry.get("Value")
                if name in needed and value:
                    result[name] = str(value)
    elif isinstance(data, dict):
        for k in needed:
            if k in data and data[k]:
                result[k] = str(data[k])
    missing = needed - result.keys()
    if missing:
        raise ValueError(f"Missing cookies: {', '.join(sorted(missing))}")
    return result


def export_cookies_netscape(session, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Netscape HTTP Cookie File"]
    for c in session.cookies:
        domain = c.domain or ""
        if not domain:
            continue
        subdomain = "TRUE" if domain.startswith(".") else "FALSE"
        expires = int(c.expires) if c.expires else 0
        secure = "TRUE" if c.secure else "FALSE"
        lines.append("\t".join([domain, subdomain, c.path or "/", secure, str(expires), c.name, c.value or ""]))
    path.write_text("\n".join(lines) + "\n")


def ytdlp_download(post_url: str, dest: Path, cookies_file: Path) -> Path:
    import yt_dlp
    dest.parent.mkdir(parents=True, exist_ok=True)
    base = dest.with_suffix("")
    opts = {
        "outtmpl": str(base) + ".%(ext)s",
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
        "quiet": True,
        "no_warnings": True,
        "cookiefile": str(cookies_file),
        "noprogress": True,
        "overwrites": True,
        "retries": 3,
        "fragment_retries": 3,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([post_url])
    for p in sorted(base.parent.glob(base.name + ".*")):
        if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".m4v"):
            if p != dest:
                p.rename(dest)
            return dest
    raise FileNotFoundError(f"No video could be downloaded for {post_url}")


def has_audio(path: Path) -> bool:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=20,
        )
        return "audio" in r.stdout.strip()
    except Exception:
        return True


def build_meta(p: "TranscribePost", transcript: str, language: Optional[str], model: str, note: Optional[str] = None) -> dict:
    meta = {
        "shortcode": p.shortcode,
        "url": f"https://www.instagram.com/p/{p.shortcode}/",
        "caption": p.caption,
        "likes": p.likes,
        "comments": p.comments,
        "views": p.views,
        "timestamp": p.timestamp,
        "transcript": transcript,
        "transcript_language": language,
        "transcribed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "whisper_model": model,
    }
    if note:
        meta["note"] = note
    return meta


def parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def make_loader() -> instaloader.Instaloader:
    kwargs = dict(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )
    # Enable the iPhone API path so Post.get_iphone_struct() works.
    # This is what gives us the accurate `play_count` that matches the
    # "views" number shown in the Instagram app.
    try:
        return instaloader.Instaloader(**kwargs, iphone_support=True)
    except TypeError:
        # Older instaloader versions don't accept iphone_support
        return instaloader.Instaloader(**kwargs)


def loader_with_session() -> instaloader.Instaloader:
    state = load_state()
    username = state.get("username")
    if not username:
        raise HTTPException(401, "Not logged in")
    session_file = SESSIONS_DIR / f"{username}.session"
    if not session_file.exists():
        raise HTTPException(401, "Session missing, re-login")
    L = make_loader()
    L.load_session_from_file(username, str(session_file))
    return L


app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(TEMPLATES_DIR / "index.html")


@app.get("/api/auth/status")
def auth_status():
    state = load_state()
    username = state.get("username")
    if not username:
        return {"logged_in": False}
    if not (SESSIONS_DIR / f"{username}.session").exists():
        return {"logged_in": False}
    return {"logged_in": True, "username": username}


class PasswordLogin(BaseModel):
    username: str
    password: str


@app.post("/api/auth/password")
def auth_password(body: PasswordLogin):
    L = make_loader()
    try:
        L.login(body.username, body.password)
    except instaloader.exceptions.BadCredentialsException:
        raise HTTPException(400, "Bad credentials")
    except instaloader.exceptions.TwoFactorAuthRequiredException:
        raise HTTPException(400, "2FA required — use cookie login instead")
    except instaloader.exceptions.ConnectionException as e:
        raise HTTPException(400, f"Instagram blocked the login: {e}")
    except Exception as e:
        raise HTTPException(400, f"Login failed: {e}")
    session_file = SESSIONS_DIR / f"{body.username}.session"
    L.save_session_to_file(str(session_file))
    save_state({"username": body.username})
    return {"ok": True, "username": body.username}


class CookieLogin(BaseModel):
    sessionid: str
    ds_user_id: str
    csrftoken: str


@app.post("/api/auth/cookies")
def auth_cookies(body: CookieLogin):
    L = make_loader()
    s = L.context._session
    for name, value in {
        "sessionid": body.sessionid,
        "ds_user_id": body.ds_user_id,
        "csrftoken": body.csrftoken,
    }.items():
        s.cookies.set(name, value, domain=".instagram.com")
    try:
        username = L.test_login()
    except Exception as e:
        raise HTTPException(400, f"Cookie check failed: {e}")
    if not username:
        raise HTTPException(400, "Cookies rejected by Instagram")
    L.context.username = username
    session_file = SESSIONS_DIR / f"{username}.session"
    L.save_session_to_file(str(session_file))
    save_state({"username": username})
    return {"ok": True, "username": username}


class CookieJsonLogin(BaseModel):
    blob: str


@app.post("/api/auth/cookies_json")
def auth_cookies_json(body: CookieJsonLogin):
    try:
        cookies = parse_cookies_blob(body.blob)
    except json.JSONDecodeError:
        raise HTTPException(400, "Not valid JSON — paste the cookies export directly")
    except ValueError as e:
        raise HTTPException(400, str(e))
    L = make_loader()
    s = L.context._session
    for name, value in cookies.items():
        s.cookies.set(name, value, domain=".instagram.com")
    try:
        username = L.test_login()
    except Exception as e:
        raise HTTPException(400, f"Cookie check failed: {e}")
    if not username:
        raise HTTPException(400, "Cookies rejected by Instagram")
    L.context.username = username
    session_file = SESSIONS_DIR / f"{username}.session"
    L.save_session_to_file(str(session_file))
    save_state({"username": username})
    return {"ok": True, "username": username}


@app.post("/api/auth/logout")
def auth_logout():
    state = load_state()
    username = state.get("username")
    if username:
        f = SESSIONS_DIR / f"{username}.session"
        if f.exists():
            f.unlink()
    save_state({})
    return {"ok": True}


def _post_views(p: instaloader.Post):
    """Return the 'views' number the IG app shows for this post.

    Order of preference:
      1. iPhone-style media endpoint `play_count` — matches IG app exactly.
         Instaloader exposes it via the `_iphone_struct` property (name
         starts with underscore but it is the public path; no callable
         alternative in instaloader 4.15).
      2. `video_play_count` property (instaloader >= 4.14.3) — may fall
         back to a GraphQL call that can also return play_count.
      3. Legacy `video_view_count` — the older "completed views" metric
         usually surfaced by the public web API. Last resort; will often
         undercount vs. what the IG app shows.
    """
    if not getattr(p, "is_video", False):
        return None

    try:
        struct = p._iphone_struct  # property access triggers the API call
        if struct:
            for key in ("play_count", "ig_play_count", "view_count"):
                v = struct.get(key)
                if v is not None:
                    return v
    except Exception:
        pass

    try:
        v = getattr(p, "video_play_count", None)
        if v is not None:
            return v
    except Exception:
        pass

    try:
        v = p.video_view_count
        if v is not None:
            return v
    except Exception:
        pass

    try:
        node = getattr(p, "_node", None) or {}
        for key in ("video_play_count", "ig_play_count", "play_count", "video_view_count", "viewer_count"):
            v = node.get(key)
            if v is not None:
                return v
    except Exception:
        pass
    return None


def serialize_post(p: instaloader.Post) -> dict:
    return {
        "shortcode": p.shortcode,
        "url": f"https://www.instagram.com/p/{p.shortcode}/",
        "caption": (p.caption or "")[:2000],
        "likes": p.likes,
        "comments": p.comments,
        "views": _post_views(p),
        "is_video": p.is_video,
        "timestamp": p.date_utc.isoformat() if p.date_utc else None,
        "thumbnail": p.url,
    }


@app.get("/api/posts/{target}")
async def stream_posts(
    target: str,
    limit: int = 200,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    target = target.strip().lstrip("@")
    df = parse_date(date_from)
    dt = parse_date(date_to)

    async def gen():
        try:
            L = loader_with_session()
        except HTTPException as e:
            yield sse_event({"error": e.detail})
            return
        try:
            profile = instaloader.Profile.from_username(L.context, target)
        except instaloader.exceptions.ProfileNotExistsException:
            yield sse_event({"error": "Profile not found"})
            return
        except Exception as e:
            yield sse_event({"error": str(e) or type(e).__name__})
            return

        yield sse_event({
            "type": "profile",
            "username": profile.username,
            "full_name": profile.full_name,
            "posts_count": profile.mediacount,
            "followers": profile.followers,
            "is_private": profile.is_private,
        })

        if profile.is_private and not profile.followed_by_viewer:
            yield sse_event({"error": "Profile is private and not followed"})
            return

        count = 0
        scanned = 0
        try:
            for post in profile.get_posts():
                scanned += 1
                post_dt = post.date_utc.replace(tzinfo=timezone.utc) if post.date_utc else None
                if df and post_dt and post_dt < df:
                    break
                if not post.is_video:
                    continue
                if dt and post_dt and post_dt > dt:
                    continue
                count += 1
                yield sse_event({"type": "post", "post": serialize_post(post)})
                if count >= limit:
                    break
                await async_human_sleep(0.25, 0.65)
        except Exception as e:
            yield sse_event({"error": "Stopped: " + (str(e) or type(e).__name__)})
            return

        yield sse_event({"type": "done", "count": count, "scanned": scanned})

    return StreamingResponse(gen(), media_type="text/event-stream")


def sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


class TranscribePost(BaseModel):
    shortcode: str
    caption: str = ""
    likes: Optional[int] = None
    comments: Optional[int] = None
    views: Optional[int] = None
    timestamp: Optional[str] = None


class TranscribeRequest(BaseModel):
    target: str
    posts: list[TranscribePost]
    model: str = "small"
    run_name: Optional[str] = None
    output_dir: Optional[str] = None


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s).strip("_") or "run"


def get_whisper(model_name: str):
    import whisper
    if model_name not in _whisper_models:
        _whisper_models[model_name] = whisper.load_model(model_name)
    return _whisper_models[model_name]


def emit(job: dict, event: dict) -> None:
    event["at"] = time.time()
    job["events"].append(event)


def run_transcribe_job(job_id: str, req: TranscribeRequest):
    job = _jobs[job_id]
    try:
        L = loader_with_session()
        target = req.target.strip().lstrip("@")
        ts = time.strftime("%Y-%m-%d_%H-%M-%S")
        run_name = safe_name(req.run_name) if req.run_name else ts

        if req.output_dir:
            base_out = Path(req.output_dir).expanduser()
            if not base_out.is_absolute():
                base_out = (ROOT / base_out).resolve()
            else:
                base_out = base_out.resolve()
        else:
            base_out = OUTPUT_DIR
        base_out.mkdir(parents=True, exist_ok=True)
        out_dir = base_out / safe_name(target)
        out_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = out_dir / f"_tmp_{run_name}"
        temp_dir.mkdir(exist_ok=True)
        final_file = out_dir / f"{run_name}.json"
        job["out_dir"] = str(out_dir)
        job["final_file"] = str(final_file)

        cookies_file = temp_dir / "cookies.txt"
        export_cookies_netscape(L.context._session, cookies_file)

        total = len(req.posts)
        emit(job, {"type": "job_start", "total": total, "target": target, "final_file": str(final_file)})
        emit(job, {"type": "phase_start", "phase": "download", "total": total})
        emit(job, {"type": "phase_start", "phase": "transcribe", "total": total})

        work_queue: Queue = Queue(maxsize=3)
        results: list[dict] = []
        results_lock = threading.Lock()

        def downloader():
            try:
                for idx, p in enumerate(req.posts):
                    if job.get("cancelled"):
                        break
                    sc = p.shortcode
                    vp = temp_dir / f"{sc}.mp4"
                    url = f"https://www.instagram.com/p/{sc}/"
                    emit(job, {"type": "item_start", "phase": "download", "index": idx, "total": total, "shortcode": sc})
                    try:
                        ytdlp_download(url, vp, cookies_file)
                        emit(job, {"type": "item_done", "phase": "download", "index": idx, "total": total, "shortcode": sc, "bytes": vp.stat().st_size})
                        work_queue.put((idx, p, vp))
                    except Exception as e:
                        emit(job, {"type": "item_error", "phase": "download", "shortcode": sc, "error": str(e) or type(e).__name__})
                    if idx < total - 1 and not job.get("cancelled"):
                        human_sleep(2.0, 5.0)
            finally:
                work_queue.put(None)

        def transcriber():
            whisper_mod = None
            while True:
                item = work_queue.get()
                if item is None:
                    break
                if job.get("cancelled"):
                    try:
                        item[2].unlink(missing_ok=True)
                    except Exception:
                        pass
                    continue
                idx, p, vp = item
                sc = p.shortcode
                emit(job, {"type": "item_start", "phase": "transcribe", "index": idx, "total": total, "shortcode": sc})
                try:
                    if not has_audio(vp):
                        meta = build_meta(p, "", None, req.model, note="no audio track")
                        emit(job, {"type": "item_skip", "phase": "transcribe", "shortcode": sc, "reason": "no audio track"})
                    else:
                        if whisper_mod is None:
                            emit(job, {"type": "log", "message": "Loading transcription model…"})
                            whisper_mod = get_whisper(req.model)
                            emit(job, {"type": "log", "message": "Transcription model ready"})
                        result = whisper_mod.transcribe(str(vp), fp16=False)
                        meta = build_meta(p, result["text"].strip(), result.get("language"), req.model)
                        emit(job, {"type": "item_done", "phase": "transcribe", "index": idx, "total": total, "shortcode": sc})
                    with results_lock:
                        results.append(meta)
                except Exception as e:
                    emit(job, {"type": "item_error", "phase": "transcribe", "shortcode": sc, "error": str(e) or type(e).__name__})
                finally:
                    vp.unlink(missing_ok=True)

        dl_thread = threading.Thread(target=downloader, daemon=True)
        tx_thread = threading.Thread(target=transcriber, daemon=True)
        dl_thread.start()
        tx_thread.start()
        dl_thread.join()
        tx_thread.join()

        summary = {
            "target": target,
            "run_name": run_name,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "whisper_model": req.model,
            "count": len(results),
            "videos": sorted(results, key=lambda r: r.get("shortcode", "")),
        }
        final_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

        _cleanup_temp(temp_dir)
        if job.get("cancelled"):
            emit(job, {"type": "job_cancelled", "final_file": str(final_file)})
        else:
            emit(job, {"type": "job_done", "final_file": str(final_file)})
        job["done"] = True
    except Exception as e:
        emit(job, {"type": "job_error", "error": str(e) or type(e).__name__})
        job["done"] = True


def _cleanup_temp(temp_dir: Path) -> None:
    try:
        for leftover in temp_dir.iterdir():
            leftover.unlink(missing_ok=True)
        temp_dir.rmdir()
    except OSError:
        pass


@app.post("/api/transcribe")
def transcribe_start(req: TranscribeRequest):
    if not req.posts:
        raise HTTPException(400, "No posts selected")
    job_id = uuid.uuid4().hex
    _jobs[job_id] = {"events": [], "done": False, "cancelled": False}
    executor.submit(run_transcribe_job, job_id, req)
    return {"job_id": job_id}


@app.get("/api/transcribe/{job_id}/events")
async def transcribe_events(job_id: str, request: Request):
    if job_id not in _jobs:
        raise HTTPException(404, "Unknown job")

    async def gen():
        sent = 0
        while True:
            if await request.is_disconnected():
                return
            job = _jobs[job_id]
            while sent < len(job["events"]):
                yield sse_event(job["events"][sent])
                sent += 1
            if job.get("done") and sent >= len(job["events"]):
                return
            await asyncio.sleep(0.3)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/transcribe/{job_id}/cancel")
def transcribe_cancel(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, "Unknown job")
    _jobs[job_id]["cancelled"] = True
    return {"ok": True}


@app.post("/api/clipboard")
def set_clipboard(body: dict):
    content = body.get("content", "")
    if not isinstance(content, str):
        raise HTTPException(400, "content must be a string")
    try:
        if sys.platform == "win32":
            subprocess.run(["clip"], input=content, text=True, check=True, timeout=10, shell=False)
        elif sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=content, text=True, check=True, timeout=10)
        else:
            for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "-b", "-i"]):
                try:
                    subprocess.run(cmd, input=content, text=True, check=True, timeout=10)
                    break
                except FileNotFoundError:
                    continue
            else:
                raise HTTPException(500, "No clipboard tool available (install xclip or xsel)")
    except FileNotFoundError:
        raise HTTPException(500, "Clipboard tool not available on this system")
    except subprocess.CalledProcessError as e:
        raise HTTPException(500, f"Copy failed: {e}")
    return {"ok": True}


@app.post("/api/reveal")
def reveal_folder(body: dict):
    path = body.get("path")
    if not path or not Path(path).exists():
        raise HTTPException(400, "Path not found")
    p = Path(path)
    if sys.platform == "win32":
        if p.is_file():
            subprocess.run(["explorer", "/select,", str(p)], check=False)
        else:
            subprocess.run(["explorer", str(p)], check=False)
    elif sys.platform == "darwin":
        if p.is_file():
            subprocess.run(["open", "-R", str(p)], check=False)
        else:
            subprocess.run(["open", str(p)], check=False)
    else:
        target = str(p) if p.is_dir() else str(p.parent)
        subprocess.run(["xdg-open", target], check=False)
    return {"ok": True}


def _scan_runs(base: Path) -> list[dict]:
    runs: list[dict] = []
    if not base.exists():
        return runs
    for target_dir in base.iterdir():
        if not target_dir.is_dir() or target_dir.name.startswith("_") or target_dir.name.startswith("."):
            continue
        for entry in target_dir.iterdir():
            if entry.name.startswith(".") or entry.name.startswith("_"):
                continue
            if entry.is_file() and entry.suffix == ".json":
                data = _safe_read_summary(entry)
                if data is None:
                    continue
                runs.append({
                    "kind": "file",
                    "path": str(entry),
                    "base": str(base),
                    "target": target_dir.name,
                    "run_name": entry.stem,
                    "generated_at": data.get("generated_at"),
                    "count": data.get("count", len(data.get("videos", []))),
                    "size": entry.stat().st_size,
                    "whisper_model": data.get("whisper_model"),
                })
            elif entry.is_dir():
                summary = entry / "_summary.json"
                if not summary.exists():
                    continue
                data = _safe_read_summary(summary)
                if data is None:
                    continue
                size = 0
                for x in entry.rglob("*"):
                    if x.is_file():
                        try:
                            size += x.stat().st_size
                        except OSError:
                            pass
                runs.append({
                    "kind": "folder",
                    "path": str(entry),
                    "base": str(base),
                    "target": target_dir.name,
                    "run_name": entry.name,
                    "generated_at": data.get("generated_at"),
                    "count": data.get("count", len(data.get("videos", []))),
                    "size": size,
                    "whisper_model": data.get("whisper_model"),
                })
    return runs


def _safe_read_summary(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    if not isinstance(data, dict) or "videos" not in data:
        return None
    return data


@app.get("/api/library")
def library_list(output_dir: Optional[str] = None):
    bases: list[Path] = [OUTPUT_DIR]
    if output_dir:
        custom = Path(output_dir).expanduser()
        if not custom.is_absolute():
            custom = (ROOT / custom).resolve()
        else:
            custom = custom.resolve()
        if custom.exists() and custom not in bases:
            bases.append(custom)
    runs: list[dict] = []
    for base in bases:
        runs.extend(_scan_runs(base))
    runs.sort(key=lambda r: r.get("generated_at") or "", reverse=True)
    return {"runs": runs}


@app.get("/api/library/file")
def library_read(path: str):
    p = Path(path).resolve()
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "Not found")
    if p.suffix != ".json":
        raise HTTPException(400, "Not a JSON file")
    try:
        content = p.read_text()
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"filename": p.name, "content": content, "size": p.stat().st_size}


class DeleteLibraryItem(BaseModel):
    path: str
    kind: str


@app.post("/api/library/delete")
def library_delete(body: DeleteLibraryItem):
    p = Path(body.path).resolve()
    if not p.exists():
        raise HTTPException(404, "Not found")
    try:
        if body.kind == "folder":
            if not p.is_dir():
                raise HTTPException(400, "Path is not a folder")
            shutil.rmtree(p)
        elif body.kind == "file":
            if not p.is_file():
                raise HTTPException(400, "Path is not a file")
            p.unlink()
            parent = p.parent
            if parent != OUTPUT_DIR and parent.exists() and not any(parent.iterdir()):
                try:
                    parent.rmdir()
                except OSError:
                    pass
        else:
            raise HTTPException(400, "Unknown kind")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True}
