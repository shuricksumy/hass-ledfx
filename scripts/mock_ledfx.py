"""Strict mock of the LedFx 2.1.9 REST API (stdlib only).

Mirrors v2.1.9 semantics closely enough to catch stale-client bugs:
  * /api/devices/{id}/effects and /api/devices/{id}/presets do not exist (404)
  * effect config keys are schema-validated (PREVENT_EXTRA) -> "active" is rejected
  * PUT /api/audio/devices reads "audio_device", not "index"
  * preset category must be ledfx_presets|user_presets
"""
import json, re, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EFFECT_KEYS = {"blur","flip","mirror","brightness","background_color",
               "background_brightness","diag","advanced","gradient","speed"}
EFFECTS = {"rainbow","wavelength","scroll"}

STATE = {
    "virtuals": {
        "my-strip": {"config": {"name": "My Strip", "icon_name": "mdi:led-strip"},
                     "id": "my-strip", "is_device": "wled-1", "auto_generated": False,
                     "segments": [], "pixel_count": 60, "active": True,
                     "streaming": False, "last_effect": None, "effect": {}},
    },
    # per-virtual saved effect configs (virtual_cfg["effects"])
    "effects_store": {"my-strip": {"rainbow": {"config": {"brightness": 0.8, "speed": 1.0}}}},
    "audio_device": 0,
}

def eff_defaults(t):
    return {"blur": 0.0, "flip": False, "mirror": False, "brightness": 1.0,
            "background_color": "#000000", "background_brightness": 1.0,
            "diag": False, "speed": 1.0}


def _preset(**overrides):
    """LedFx stores presets as complete effect configs, not partial overrides."""
    return {**eff_defaults(None), **overrides}


LEDFX_PRESETS = {
    "rainbow": {
        "slow-roll": {"name": "Slow Roll", "config": _preset(brightness=0.6, speed=0.3)},
        "blazing": {"name": "Blazing", "config": _preset(brightness=1.0, speed=4.0)},
    }
}
USER_PRESETS = {"rainbow": {"my": {"name": "My", "config": _preset(brightness=0.42, blur=2.0)}}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bad(self, reason):
        # LedFx returns 400 with status=failed for invalid requests
        self._send(400, {"status": "failed", "payload": {"type": "error", "reason": reason}})

    def _err202(self, reason):
        # generic handler exception path in ledfx/api/__init__.py
        self._send(202, {"status": "failed", "payload": {"type": "error", "reason": reason}})

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return None
        try:
            return json.loads(self.rfile.read(n))
        except Exception:
            return "___JSONERR___"

    def _validate_cfg(self, cfg):
        bad = [k for k in cfg if k not in EFFECT_KEYS]
        if bad:
            raise ValueError(f"extra keys not allowed @ data[{bad[0]!r}]")

    # ---- dispatch -------------------------------------------------------
    def do_GET(self):    self._route("GET")
    def do_PUT(self):    self._route("PUT")
    def do_POST(self):   self._route("POST")
    def do_DELETE(self): self._route("DELETE")

    def _route(self, method):
        p = self.path.split("?")[0].rstrip("/")
        body = self._body()
        if body == "___JSONERR___":
            return self._bad("JSON decode error")

        # --- routes that no longer exist in 2.x ---
        if re.fullmatch(r"/api/devices/[^/]+/(effects|presets)", p):
            return self._send(404, {"status": "failed", "reason": "Not Found"})

        if p == "/api/info" and method == "GET":
            return self._send(200, {"url": "http://127.0.0.1:8888", "name": "LedFx Controller",
                                    "version": "2.1.9", "github_sha": "unknown",
                                    "is_release": "true", "developer_mode": False,
                                    "features": {"sendspin": False}})

        if p == "/api/config" and method == "GET":
            return self._send(200, {
                "configuration_version": "2.3.6", "host": "0.0.0.0", "port": 8888,
                "dev_mode": False, "scenes": {}, "playlists": {},
                "audio": {"audio_device": STATE["audio_device"], "audio_device_name": "Mic",
                          "min_volume": 0.2, "sample_rate": 60, "mic_rate": 44100,
                          "fft_size": 4096, "delay_ms": 0},
                "ledfx_presets": LEDFX_PRESETS, "user_presets": USER_PRESETS,
                "global_brightness": 1.0, "wled_preferences": {}, "melbanks": {},
            })

        if p == "/api/config" and method == "PUT":
            audio = (body or {}).get("audio", {})
            if "audio_device" in audio:
                STATE["audio_device"] = audio["audio_device"]
            return self._send(200, {"status": "success"})

        if p == "/api/devices" and method == "GET":
            return self._send(200, {"status": "success", "devices": {
                "wled-1": {"config": {"name": "WLED 1", "ip_address": "10.0.0.5"},
                           "id": "wled-1", "type": "wled", "online": True,
                           "virtuals": ["my-strip"], "active_virtuals": ["my-strip"]}}})

        if p == "/api/virtuals" and method == "GET":
            return self._send(200, {"status": "success", "paused": False,
                                    "virtuals": STATE["virtuals"]})

        if p == "/api/scenes" and method == "GET":
            return self._send(200, {"status": "success",
                                    "scenes": {"party": {"name": "Party", "virtuals": {}, "active": False}}})

        if p == "/api/scenes" and method == "PUT":
            b = body or {}
            if b.get("action") not in ("activate", "deactivate", "activate_in", "rename"):
                return self._bad("Invalid action")
            if not b.get("id"):
                return self._bad('Required attribute "id" was not provided')
            return self._send(200, {"status": "success",
                                    "payload": {"type": "info", "reason": "Activated Party"}})

        if p == "/api/schema" and method == "GET":
            return self._send(200, {
                "devices": {"wled": {"schema": {"properties": {}}, "id": "wled"}},
                "effects": {e: {"schema": {"properties": {
                    "brightness": {"type": "number", "title": "Brightness", "minimum": 0.0, "maximum": 1.0},
                    "speed": {"type": "number", "title": "Speed", "minimum": 0.0, "maximum": 5.0},
                    "flip": {"type": "boolean", "title": "Flip"},
                    "background_color": {"type": "color", "gradient": False, "title": "Background Color"},
                }}, "id": e, "name": e.title(), "category": "Non-Reactive"} for e in EFFECTS},
                "audio": {"schema": {"properties": {
                    "audio_device": {"type": "string", "title": "Audio Device",
                                     "enum": {"0": "Built-in Mic", "1": "Loopback"}}}}},
                "virtuals": {"schema": {"properties": {}}},
            })

        if p == "/api/colors" and method == "GET":
            return self._send(200, {"colors": {"builtin": {"red": "#ff0000"}, "user": {}},
                                    "gradients": {"builtin": {"rainbow": "linear-gradient(90deg,red,blue)"}, "user": {}}})

        if p == "/api/audio/devices" and method == "GET":
            return self._send(200, {"devices": {"0": "Built-in Mic", "1": "Loopback"},
                                    "active_device_index": STATE["audio_device"],
                                    "active_device_name": "Built-in Mic"})

        if p == "/api/audio/devices" and method == "PUT":
            b = body or {}
            idx = b.get("audio_device")          # <-- 2.x key
            if idx is None:
                return self._bad("Required attribute 'index' was not provided")
            if idx not in (0, 1):
                return self._bad(f"Invalid device index [{idx}]")
            STATE["audio_device"] = idx
            return self._send(200, {"status": "success"})

        m = re.fullmatch(r"/api/virtuals/([^/]+)/effects", p)
        if m:
            vid = m.group(1)
            v = STATE["virtuals"].get(vid)
            if v is None:
                return self._bad(f"Virtual with ID {vid} not found")

            if method == "POST":
                b = body or {}
                t = b.get("type")
                if t is None:
                    return self._bad("Required attribute 'type' was not provided")
                if t not in EFFECTS:
                    return self._err202(f"Couldn't find '{t}' in the effect registry")
                cfg = b.get("config")
                if cfg is None:
                    cfg = STATE["effects_store"].get(vid, {}).get(t, {}).get("config", {})
                try:
                    self._validate_cfg(cfg)
                except ValueError as e:
                    return self._err202(str(e))     # vol.Invalid -> generic handler
                merged = {**eff_defaults(t), **cfg}
                v["effect"] = {"config": merged, "name": t.title(), "type": t}
                STATE["effects_store"].setdefault(vid, {})[t] = {"config": merged}
                return self._send(200, {"status": "success", "effect": v["effect"]})

            if method == "PUT":
                if not v["effect"]:
                    return self._bad(f"Virtual {vid} has no active effect")
                b = body or {}
                cfg = b.get("config") or {}
                try:
                    self._validate_cfg(cfg)
                except ValueError as e:
                    return self._err202(str(e))
                t = b.get("type") or v["effect"]["type"]
                merged = {**v["effect"]["config"], **cfg} if t == v["effect"]["type"] else {**eff_defaults(t), **cfg}
                v["effect"] = {"config": merged, "name": t.title(), "type": t}
                STATE["effects_store"].setdefault(vid, {})[t] = {"config": merged}
                return self._send(200, {"status": "success", "effect": v["effect"]})

            if method == "DELETE":
                v["effect"] = {}
                return self._send(200, {"status": "success", "effect": {}})

        m = re.fullmatch(r"/api/virtuals/([^/]+)/effects/delete", p)
        if m and method == "POST":
            vid = m.group(1)
            v = STATE["virtuals"].get(vid)
            if v is None:
                return self._bad(f"Virtual with ID {vid} not found")
            t = (body or {}).get("type")
            if t is None:
                return self._bad("Required attribute 'type' was not provided")
            if v["effect"].get("type") == t:
                v["effect"] = {}
            STATE["effects_store"].get(vid, {}).pop(t, None)
            return self._send(200, {"status": "success"})

        m = re.fullmatch(r"/api/virtuals/([^/]+)/presets", p)
        if m and method == "PUT":
            vid = m.group(1)
            v = STATE["virtuals"].get(vid)
            if v is None:
                return self._bad(f"Virtual with ID {vid} not found")
            b = body or {}
            cat, eid, pid = b.get("category"), b.get("effect_id"), b.get("preset_id")
            missing = [n for n, x in (("category", cat), ("preset_id", pid), ("effect_id", eid)) if x is None]
            if missing:
                return self._bad(f'Required attributes {", ".join(missing)} were not provided')
            if cat not in ("ledfx_presets", "user_presets"):
                return self._bad(f'Category {cat} is not "ledfx_presets" or "user_presets"')
            table = LEDFX_PRESETS if cat == "ledfx_presets" else USER_PRESETS
            if eid not in table:
                return self._bad(f"Effect {eid} does not exist in category {cat}")
            if pid not in table[eid]:
                return self._bad(f"Preset {pid} does not exist for effect {eid} in category {cat}")
            merged = {**eff_defaults(eid), **table[eid][pid]["config"]}
            v["effect"] = {"config": merged, "name": eid.title(), "type": eid}
            return self._send(200, {"status": "success", "effect": v["effect"]})

        return self._send(404, {"status": "failed", "reason": f"no route {method} {p}"})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
