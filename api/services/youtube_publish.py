"""YouTube publishing for connected suites.

**The one thing that makes this unlike every other platform here:** Meta takes a
URL and pulls the file itself, so `publisher._resolve_url()` is all it needs.
YouTube does not accept a URL at all — it wants the bytes, over a resumable
session. So the file is streamed from R2 (or the local static dir) into a temp
file and pushed to YouTube in 8MB chunks.

Quota is the real ceiling, not the code: an upload costs **1,600 units** out of
10,000 per day, counted per **Google Cloud project** — shared across every suite
on the platform. A caption track is +400, a thumbnail +50.
"""
import json
import logging
import mimetypes
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from ..core.config import settings
from ..models.content import ContentPost
from .media_storage import platform_media_for_post
from .youtube_oauth import GOOGLE_TOKEN_URL, YOUTUBE_API

log = logging.getLogger(__name__)

YT_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
YT_CAPTIONS = "https://www.googleapis.com/upload/youtube/v3/captions"

API_ROOT = Path(__file__).parent.parent
# Must be a multiple of 256KB — YouTube rejects anything else on a middle chunk.
CHUNK = 8 * 1024 * 1024
TITLE_MAX = 100
DESCRIPTION_MAX = 5000
TAGS_CHARS_MAX = 500


# ── Auth (sync) ───────────────────────────────────────────────────────────────
#
# youtube_oauth's helpers are async because they serve FastAPI routes. publish_post
# is sync and runs off the event loop, so the two calls it needs live here in sync
# form rather than being awaited from a thread.

def access_token(refresh_token: str) -> str:
    r = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": settings.youtube_client_id,
            "client_secret": settings.youtube_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Token refresh failed [{r.status_code}]: {r.text}")
    return r.json()["access_token"]


def authorized_channel(token: str) -> dict:
    r = httpx.get(
        f"{YOUTUBE_API}/channels",
        params={"part": "snippet", "mine": "true"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Channel lookup failed [{r.status_code}]: {r.text}")
    items = r.json().get("items") or []
    if not items:
        raise RuntimeError("This authorization has no YouTube channel.")
    return {
        "channel_id": items[0].get("id"),
        "channel_title": (items[0].get("snippet") or {}).get("title"),
    }


# ── Source bytes ──────────────────────────────────────────────────────────────

def _download_to_temp(url_or_path: str) -> tuple[Path, int]:
    """Stream the source to a temp file and return (path, size).

    Streamed rather than held in memory: a suite's video is routinely 50-200MB and
    the API process is not sized for that per request.
    """
    tmp = Path(tempfile.mkstemp(prefix="yt-upload-")[1])
    if url_or_path.startswith("https://"):
        with httpx.stream("GET", url_or_path, timeout=300, follow_redirects=True) as r:
            if r.status_code >= 400:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"Could not fetch media [{r.status_code}]: {url_or_path}")
            with tmp.open("wb") as f:
                for block in r.iter_bytes(1024 * 256):
                    f.write(block)
    else:
        local = API_ROOT / url_or_path.lstrip("/")
        if not local.exists():
            tmp.unlink(missing_ok=True)
            raise FileNotFoundError(f"Media not found on disk: {local}")
        tmp.write_bytes(local.read_bytes())
    return tmp, tmp.stat().st_size


# ── Resumable upload ──────────────────────────────────────────────────────────

def _upload_offset(session: str, total: int) -> int:
    """Ask YouTube how much it actually has, after a chunk fails mid-flight."""
    r = httpx.put(session, headers={"Content-Range": f"bytes */{total}"}, timeout=60)
    if r.status_code in (200, 201):
        return total
    rng = r.headers.get("Range")
    return int(rng.split("-")[1]) + 1 if rng else 0


def upload_video(token: str, path: Path, size: int, body: dict, notify: bool = True) -> dict:
    init = httpx.post(
        YT_UPLOAD,
        params={"part": "snippet,status", "notifySubscribers": str(bool(notify)).lower()},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": mimetypes.guess_type(path.name)[0] or "video/*",
        },
        content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        timeout=60,
    )
    if init.status_code >= 400:
        raise RuntimeError(f"YouTube rejected the upload request [{init.status_code}]: {init.text}")
    session = init.headers.get("Location")
    if not session:
        raise RuntimeError("YouTube did not return a resumable upload session.")

    start = 0
    with path.open("rb") as f:
        while start < size:
            f.seek(start)
            data = f.read(CHUNK)
            end = start + len(data) - 1
            r = httpx.put(
                session,
                headers={"Content-Range": f"bytes {start}-{end}/{size}"},
                content=data,
                timeout=600,
            )
            if r.status_code in (200, 201):
                return r.json()
            if r.status_code == 308:
                start = end + 1
                continue
            if r.status_code in (500, 502, 503, 504):
                start = _upload_offset(session, size)
                continue
            raise RuntimeError(f"Upload failed [{r.status_code}]: {r.text}")
    raise RuntimeError("Upload finished without a final response from YouTube.")


def insert_caption(token: str, video_id: str, srt: bytes, lang: str = "ar") -> str:
    """Attach a caption track.

    `captions.insert` rejects the `youtube.upload` scope — this is the reason the
    connection also asks for `youtube.force-ssl`. The multipart/related body is
    hand-built because httpx sends multipart/form-data, which YouTube refuses.
    """
    boundary = "==cosuite-yt-caption=="
    meta = json.dumps(
        {"snippet": {"videoId": video_id, "language": lang, "name": "", "isDraft": False}},
        ensure_ascii=False,
    ).encode("utf-8")
    payload = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
        + meta
        + f"\r\n--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
        + srt
        + f"\r\n--{boundary}--\r\n".encode()
    )
    r = httpx.post(
        YT_CAPTIONS,
        params={"part": "snippet", "uploadType": "multipart"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        content=payload,
        timeout=120,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Caption upload failed [{r.status_code}]: {r.text}")
    return (r.json() or {}).get("id", "")


def verify_video(token: str, video_id: str) -> dict:
    """Read the video back from YouTube.

    An API project that has not passed the YouTube compliance audit accepts a
    `public` upload and silently stores it as `private`, with no error anywhere.
    The only way to know what actually happened is to ask.
    """
    r = httpx.get(
        f"{YOUTUBE_API}/videos",
        params={"part": "status", "id": video_id},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if r.status_code >= 400:
        return {}
    items = r.json().get("items") or []
    return (items[0].get("status") or {}) if items else {}


# ── Entry point ───────────────────────────────────────────────────────────────

def _youtube_options(post: ContentPost) -> dict:
    return ((post.ai_metadata or {}).get("youtube") or {})


def _build_body(post: ContentPost, opts: dict) -> dict:
    title = (opts.get("title") or post.topic or "").strip()
    if not title:
        raise ValueError("YouTube needs a title. Set ai_metadata.youtube.title or the post topic.")
    if len(title) > TITLE_MAX:
        raise ValueError(f"YouTube title is {len(title)} characters; the limit is {TITLE_MAX}.")

    description = (opts.get("description") or post.caption or "")[:DESCRIPTION_MAX]
    # YouTube rejects the whole upload on these two, rather than escaping them.
    for field, value in (("title", title), ("description", description)):
        if "<" in value or ">" in value:
            raise ValueError(f"YouTube does not allow < or > in the {field}.")

    tags = [t.lstrip("#") for t in (post.hashtags or []) if isinstance(t, str) and t.strip()]
    if sum(len(t) for t in tags) > TAGS_CHARS_MAX:
        raise ValueError(
            f"Tags total {sum(len(t) for t in tags)} characters; YouTube caps them at "
            f"{TAGS_CHARS_MAX} and rejects the whole upload over it."
        )

    # Not defaulted on purpose: "made for kids" is a legal declaration to the FTC,
    # not a formatting choice, and guessing it for a client is not ours to do.
    made_for_kids = opts.get("made_for_kids")
    if not isinstance(made_for_kids, bool):
        raise ValueError(
            "YouTube requires an explicit audience declaration. "
            "Set ai_metadata.youtube.made_for_kids to true or false."
        )

    privacy = opts.get("privacy", "public")
    if privacy not in ("public", "unlisted", "private"):
        raise ValueError(f"Unknown privacy setting: {privacy}")

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": str(opts.get("category_id", "22")),
            "defaultLanguage": opts.get("language", "ar"),
            "defaultAudioLanguage": opts.get("language", "ar"),
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": made_for_kids,
            "embeddable": True,
            "license": "youtube",
        },
    }
    if opts.get("publish_at"):
        # Native YouTube scheduling only works from private.
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = opts["publish_at"]
    return body


def publish_to_youtube(post: ContentPost, connections: dict) -> dict:
    """Upload one post's video to the suite's connected channel."""
    yt = connections.get("youtube") or {}
    refresh_token = yt.get("refresh_token")
    if not refresh_token:
        return {"youtube_error": "YouTube not connected"}

    urls = platform_media_for_post(post, "youtube")
    if not urls:
        return {"youtube_error": "YouTube needs a video file on the post."}

    opts = _youtube_options(post)
    try:
        body = _build_body(post, opts)
    except ValueError as e:
        return {"youtube_error": str(e)}

    tmp: Optional[Path] = None
    try:
        token = access_token(refresh_token)
    except Exception as e:
        return {"youtube_error": f"Could not refresh the YouTube authorization: {e}"}

    try:
        # Confirm the target before spending quota: the cost of a stale token is a
        # client's video on somebody else's channel, which cannot be undone quietly.
        channel = authorized_channel(token)
        expected = yt.get("channel_id")
        if expected and channel.get("channel_id") != expected:
            return {
                "youtube_error": (
                    f"This authorization now points at {channel.get('channel_title')} "
                    f"({channel.get('channel_id')}), not the connected channel {expected}. "
                    "Reconnect YouTube before publishing."
                )
            }

        tmp, size = _download_to_temp(urls[0])
        result = upload_video(token, tmp, size, body, notify=opts.get("notify", True))
        video_id = result.get("id", "")
        if not video_id:
            return {"youtube_error": "YouTube accepted the upload but returned no video id."}

        out: dict = {"youtube": video_id, "youtube_url": f"https://www.youtube.com/watch?v={video_id}"}

        srt = opts.get("captions_srt")
        if srt:
            try:
                insert_caption(token, video_id, srt.encode("utf-8"), opts.get("language", "ar"))
                out["youtube_captions"] = True
            except Exception as e:
                out["youtube_warning"] = f"Video published, captions failed: {e}"

        actual = verify_video(token, video_id).get("privacyStatus")
        requested = body["status"]["privacyStatus"]
        out["youtube_privacy"] = actual or requested
        if actual and actual != requested:
            out["youtube_warning"] = (
                f"Requested {requested} but YouTube stored it as {actual}. "
                "This is the unverified-project lock — the API cannot reopen it."
            )
        log.info("YouTube published: %s (%s)", video_id, out["youtube_privacy"])
        return out
    except Exception as e:
        log.exception("YouTube publish failed")
        return {"youtube_error": str(e)}
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
