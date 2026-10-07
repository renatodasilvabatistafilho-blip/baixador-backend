import os, hmac, hashlib, time, tempfile, shutil, re
from urllib.parse import urlparse
from flask import Flask, request, jsonify, send_file
import yt_dlp

app = Flask(__name__)

SECRET = os.environ.get("SECRET", "")
MAX_DURATION = int(os.environ.get("MAX_DURATION", 3600))        # segundos
MAX_FILESIZE = int(os.environ.get("MAX_FILESIZE_MB", 500)) * 1024 * 1024
COOKIES_FILE = os.environ.get("COOKIES_FILE", "")                # opcional (YouTube)

ALLOWED = [d.strip() for d in os.environ.get("ALLOWED_HOSTS",
    "tiktok.com,youtube.com,youtu.be,instagram.com,facebook.com,fb.watch,"
    "twitter.com,x.com,vimeo.com,reddit.com,pinterest.com,pin.it,soundcloud.com,"
    "twitch.tv,kwai.com,kuaishou.com,dailymotion.com,streamable.com").split(",") if d.strip()]


def host_ok(url: str) -> bool:
    p = urlparse(url)
    h = (p.hostname or "").lower()
    return p.scheme in ("http", "https") and any(h == d or h.endswith("." + d) for d in ALLOWED)


def sign(url: str, kind: str, exp: str) -> str:
    return hmac.new(SECRET.encode(), f"{url}|{kind}|{exp}".encode(), hashlib.sha256).hexdigest()


def base_opts(tmp: str) -> dict:
    o = {"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 20}
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        dst = os.path.join(tmp, "cookies.txt")      # cópia: o yt-dlp escreve no ficheiro
        shutil.copy(COOKIES_FILE, dst)
        o["cookiefile"] = dst
    return o


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/info")
def info():
    if not SECRET or not hmac.compare_digest(request.headers.get("X-API-Key", ""), SECRET):
        return jsonify(erro="Não autorizado."), 401
    url = (request.get_json(silent=True) or {}).get("url", "")
    if not host_ok(url):
        return jsonify(erro="Este site não é suportado."), 400
    tmp = tempfile.mkdtemp()
    try:
        opts = base_opts(tmp) | {"skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            d = ydl.extract_info(url, download=False)
        if d.get("duration") and d["duration"] > MAX_DURATION:
            return jsonify(erro="Vídeo demasiado longo."), 400
        return jsonify(titulo=d.get("title") or "Sem título", thumb=d.get("thumbnail"),
                       duracao=d.get("duration"), autor=d.get("uploader"))
    except Exception as e:
        msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e))[:300]
        return jsonify(erro=msg), 422
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.get("/download")
def download():
    url = request.args.get("url", "")
    kind = request.args.get("kind", "video")
    exp = request.args.get("exp", "0")
    sig = request.args.get("sig", "")
    if not SECRET or kind not in ("video", "audio") or not exp.isdigit() or int(exp) < time.time() \
            or not hmac.compare_digest(sig, sign(url, kind, exp)) or not host_ok(url):
        return "Link inválido ou expirado. Volta a analisar o link.", 403

    tmp = tempfile.mkdtemp()
    try:
        opts = base_opts(tmp) | {
            "outtmpl": os.path.join(tmp, "%(title).80B [%(id)s].%(ext)s"),
            "max_filesize": MAX_FILESIZE,
            "restrictfilenames": False,
        }
        if kind == "audio":
            opts |= {"format": "bestaudio/best",
                     "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                                         "preferredquality": "192"}]}
        else:
            opts |= {"format": "bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/bv*+ba/b",
                     "merge_output_format": "mp4"}
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
        files = [f for f in os.listdir(tmp) if f != "cookies.txt"]
        if not files:
            raise RuntimeError("Nada foi descarregado.")
        path = os.path.join(tmp, files[0])
        resp = send_file(path, as_attachment=True, download_name=files[0])
        resp.call_on_close(lambda: shutil.rmtree(tmp, ignore_errors=True))
        return resp
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return "Erro: " + re.sub(r"\x1b\[[0-9;]*m", "", str(e))[:300], 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
