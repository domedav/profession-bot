#!/usr/bin/env python3
"""Flask webfelület a Profession Bothoz (csak localhost)."""
import threading, queue, asyncio, json, csv, webbrowser
import argparse
import builtins
from flask import Flask, jsonify, request, send_from_directory
import autoapply as bot
app = Flask(__name__, static_folder="static", static_url_path="/static")
BASE_DIR = bot.BASE_DIR
CONFIG_PATH = BASE_DIR / "config.json"
SESSION_PATH = BASE_DIR / "session.json"
LOG_PATH = BASE_DIR / "apply_log.csv"
STATS_PATH = BASE_DIR / "run_stats.json"
FULL_LOG_PATH = BASE_DIR / "full_log.txt"
ORIGINAL_INPUT = builtins.input
PASSWORD_MASK = "***"
PASSWORD_KEYS = {"user_password", "password", "passwd", "jelszo", "jelszó"}

class BotManager:
    def __init__(self):
        self.state = {"state": "idle", "dry_run": False, "guided": False,
                      "pending_question": None, "progress": {}}
        self.input_q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
    def is_running(self) -> bool:
        with self._lock:
            return self.state["state"] == "running"
    def start(self, dry_run=False, guided=False) -> bool:
        with self._lock:
            if self.state["state"] == "running":
                return False
            self.state.update({"state": "running", "dry_run": dry_run,
                               "guided": guided, "pending_question": None, "progress": {}})
            self.stop_event.clear()
            while not self.input_q.empty():
                try: self.input_q.get_nowait()
                except queue.Empty: break
        self.worker = threading.Thread(target=self._run_worker, args=(dry_run, guided), daemon=True)
        self.worker.start()
        return True
    def stop(self) -> None:
        self.stop_event.set()
        try: self.input_q.put_nowait("")
        except Exception: pass
        with self._lock:
            self.state["state"] = "idle"
            self.state["pending_question"] = None
    def answer(self, answer: str) -> bool:
        with self._lock:
            if self.state["pending_question"] is None:
                return False
            self.state["pending_question"] = None
        self.input_q.put(answer)
        return True
    def _web_input(self, prompt: str = "") -> str:
        with self._lock:
            self.state["pending_question"] = str(prompt)
        value = self.input_q.get()
        return value if isinstance(value, str) else str(value)
    def _run_worker(self, dry_run: bool, guided: bool) -> None:
        old_handler = getattr(bot, "WEB_INPUT_HANDLER", None)
        old_input = builtins.input
        old_prompts: list = []
        try:
            bot.WEB_INPUT_HANDLER = self._web_input
            builtins.input = self._web_input
            # Rich Prompt/Confirm/IntPrompt megkerülik builtins.input-ot,
            # ezért webes futás alatt ezeket is átirányítjuk.
            try:
                from rich.prompt import Prompt as _P, Confirm as _C, IntPrompt as _I
                def _ask(prompt="", **kw):
                    choices = kw.get("choices")
                    q = str(prompt) + (f" [{'/'.join(choices)}]" if choices else "")
                    return self._web_input(q)
                def _confirm(prompt="", **kw):
                    ans = self._web_input(str(prompt) + " [y/n]").strip().lower()
                    return ans in ("y", "yes", "i", "igen")
                for _cls, _fn in ((_P, "ask"), (_C, "ask"), (_I, "ask")):
                    old_prompts.append((_cls, _fn, getattr(_cls, _fn)))
                    if _fn == "ask" and _cls.__name__ == "Confirm":
                        setattr(_cls, _fn, classmethod(lambda cls, p="", **k: _confirm(p, **k)))
                    else:
                        setattr(_cls, _fn, classmethod(lambda cls, p="", **k: _ask(p, **k)))
            except ImportError:
                pass
            asyncio.run(self._run_bot(dry_run, guided))
        except Exception as e:
            try:
                with open(FULL_LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(f"worker error: {e}\n")
            except OSError: pass
        finally:
            try:
                bot.WEB_INPUT_HANDLER = old_handler
                builtins.input = old_input
                for _cls, _fn, _orig in old_prompts:
                    setattr(_cls, _fn, _orig)
            except Exception: pass
            with self._lock:
                self.state["state"] = "idle"
                self.state["pending_question"] = None
    async def _run_bot(self, dry_run: bool, guided: bool) -> None:
        cfg = bot.load_config() if hasattr(bot, "load_config") else {}
        instance = bot.ProfessionBot(cfg, dry_run=dry_run, guided=guided)
        setattr(instance, "stop_event", self.stop_event)
        with self._lock:
            self.state["progress"] = {"stage": "starting"}
        try:
            await instance.run()
            with self._lock:
                if not self.stop_event.is_set():
                    self.state["progress"] = {"stage": "done"}
        except Exception as e:
            with self._lock:
                self.state["progress"] = {"stage": "error", "error": str(e)[:500]}
            raise

manager = BotManager()


def _read_text(path, default=""):
    """Read a text file under BASE_DIR, return default on error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def _read_json(path, default):
    """Read a JSON file under BASE_DIR, return default on error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    except (OSError, json.JSONDecodeError):
        return default


def _mask_config(cfg: dict) -> dict:
    masked = dict(cfg)
    for key in PASSWORD_KEYS:
        if key in masked and masked[key]:
            masked[key] = PASSWORD_MASK
    return masked

@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR / "static"), "index.html")

for _page in ("guide.html", "config.html", "logs.html", "stats.html", "help.html"):
    app.add_url_rule(f"/{_page}", endpoint=f"page_{_page}",
                     view_func=lambda _p=_page: send_from_directory(str(BASE_DIR / "static"), _p))

@app.route("/api/status")
def api_status():
    s = dict(manager.state)
    s["running"] = (s.get("state") == "running")
    s["status"] = s.get("state", "")
    return jsonify(s)

@app.route("/api/start", methods=["POST"])
def api_start():
    if manager.is_running():
        return jsonify({"error": "a bot már fut"}), 409
    data = request.get_json(silent=True) or {}
    manager.start(dry_run=bool(data.get("dry_run", False)), guided=bool(data.get("guided", False)))
    return jsonify(manager.state)

@app.route("/api/stop", methods=["POST"])
def api_stop():
    manager.stop()
    return jsonify(manager.state)

@app.route("/api/answer", methods=["POST"])
def api_answer():
    data = request.get_json(silent=True) or {}
    if not manager.answer(str(data.get("answer", ""))):
        return jsonify({"error": "nincs függőben lévő kérdés"}), 400
    return jsonify({"ok": True})

@app.route("/api/config", methods=["GET", "PUT"])
def api_config():
    if request.method == "GET":
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f: cfg = json.load(f)
        except (OSError, json.JSONDecodeError): cfg = {}
        return jsonify(_mask_config(cfg))
    data = request.get_json(silent=True) or {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f: current = json.load(f)
    except (OSError, json.JSONDecodeError): current = {}
    merged = dict(current)
    for key, value in data.items():
        if key in PASSWORD_KEYS and (value == PASSWORD_MASK or value == ""): continue
        merged[key] = value
    issues = bot.validate_config(merged) if hasattr(bot, "validate_config") else []
    if issues:
        return jsonify({"error": "érvénytelen beállítás", "issues": issues}), 400
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
    except OSError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(_mask_config(merged))

@app.route("/api/logs")
def api_logs():
    try: tail = int(request.args.get("tail", 200))
    except (ValueError, TypeError): tail = 200
    try:
        with open(FULL_LOG_PATH, "r", encoding="utf-8") as f: lines = f.read().splitlines()
    except OSError: lines = []
    return jsonify({"logs": lines[-tail:] if tail > 0 else []})

@app.route("/api/history")
def api_history():
    try: limit = int(request.args.get("limit", 100))
    except (ValueError, TypeError): limit = 100
    rows: list[dict] = []
    try:
        with open(LOG_PATH, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f): rows.append(row)
    except OSError: rows = []
    rows.reverse()
    return jsonify({"history": rows[:limit] if limit > 0 else []})

@app.route("/api/stats")
def api_stats():
    try:
        with open(STATS_PATH, "r", encoding="utf-8") as f: data = json.load(f)
    except (OSError, json.JSONDecodeError): data = {}
    return jsonify(data)

@app.route("/api/session/clear", methods=["POST"])
def api_session_clear():
    try: SESSION_PATH.unlink(missing_ok=True)
    except OSError as e: return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not args.no_browser:
        webbrowser.open(f"http://127.0.0.1:{args.port}/")
    app.run("127.0.0.1", port=args.port)
