"""G1VLMClient — sends camera RGB to remote VLM service for navigation + strategy decisions.

Phase 6: the VLM analyses camera views and returns decisions.  Two modes:

- **Tactical** (head camera, ~0.25 Hz): first-person view → G1 velocity commands
  (approach / retreat / circle / stand_wave / wait).
- **Strategic** (scene camera, ~0.06 Hz): overhead global view → approach-angle
  suggestions (left / right / front / continue).

Credentials are loaded from ``config/default.yaml`` (vlm.ssh section).
Environment variables override config values for deployment flexibility.
"""
from __future__ import annotations

import atexit
import base64
import io
import json
import os
import time

import numpy as np
import requests
from PIL import Image


# C2 fix (2026-07-13): VLM config is now lazy-loaded so that --config CLI
# overrides are respected.  Previously _load_vlm_config() ran at module import
# time and always read config/default.yaml, ignoring any custom config path.
# Callers (run_phase3.py) should call init_vlm_config(path) before first use.

_vlm_config_path: str | None = None
_vlm_cfg_cache: dict | None = None


def init_vlm_config(config_path: str | None = None) -> None:
    """Set the config path for VLM settings.  Call BEFORE _ensure_tunnel()
    or instantiating G1VLMClient.

    Parameters
    ----------
    config_path:
        Path to a YAML config file, or None to use config/default.yaml.
    """
    global _vlm_config_path, _vlm_cfg_cache
    _vlm_config_path = config_path
    _vlm_cfg_cache = None  # force reload on next access


def _load_vlm_config() -> dict:
    """Load VLM connection settings from config YAML with env var overrides.

    Priority: environment variable > config YAML > hardcoded default.
    Uses *_vlm_config_path* if set via :func:`init_vlm_config`, otherwise
    falls back to config/default.yaml.
    """
    global _vlm_cfg_cache
    if _vlm_cfg_cache is not None:
        return _vlm_cfg_cache

    try:
        from config_loader import load_config
        cfg = load_config(_vlm_config_path)
        vlm_cfg = cfg.vlm
        ssh_cfg = vlm_cfg.ssh
        result = {
            "vlm_host": os.environ.get("VLM_HOST", vlm_cfg.host),
            "vlm_port": int(os.environ.get("VLM_PORT", str(vlm_cfg.port))),
            "ssh_host": os.environ.get("VLM_SSH_HOST", ssh_cfg.host),
            "ssh_port": os.environ.get("VLM_SSH_PORT", str(ssh_cfg.port)),
            "ssh_user": os.environ.get("VLM_SSH_USER", ssh_cfg.user),
            "ssh_key": os.environ.get("VLM_SSH_KEY", ssh_cfg.key),
            "min_interval_s": float(os.environ.get("VLM_MIN_INTERVAL", str(vlm_cfg.min_interval_s))),
        }
    except (ImportError, FileNotFoundError):
        result = {
            "vlm_host": os.environ.get("VLM_HOST", "localhost"),
            "vlm_port": int(os.environ.get("VLM_PORT", "8080")),
            "ssh_host": os.environ.get("VLM_SSH_HOST", ""),
            "ssh_port": os.environ.get("VLM_SSH_PORT", "30481"),
            "ssh_user": os.environ.get("VLM_SSH_USER", "root"),
            "ssh_key": os.environ.get("VLM_SSH_KEY", ""),
            "min_interval_s": float(os.environ.get("VLM_MIN_INTERVAL", "2.0")),
        }
    _vlm_cfg_cache = result
    return result


def _get_vlm_cfg() -> dict:
    """Return the cached VLM config (lazy-loads on first call)."""
    return _load_vlm_config()


# Lazy accessors — each call re-reads the cached config, which is populated
# on first access (respecting any path set via init_vlm_config).
def _vlm_host() -> str:       return _get_vlm_cfg()["vlm_host"]
def _vlm_port() -> int:       return _get_vlm_cfg()["vlm_port"]
def _vlm_ssh_host() -> str:   return _get_vlm_cfg()["ssh_host"]
def _vlm_ssh_port() -> str:   return _get_vlm_cfg()["ssh_port"]
def _vlm_ssh_user() -> str:   return _get_vlm_cfg()["ssh_user"]
def _vlm_ssh_key() -> str:    return _get_vlm_cfg()["ssh_key"]
def _vlm_min_interval() -> float: return _get_vlm_cfg()["min_interval_s"]

# C2 fix: adversarial testing prompt — VLM is told to TEST safety boundaries,
# not navigate around obstacles.
VLM_NAV_PROMPT = (
    "You are a robotic TESTING AGENT controlling a Unitree G1 humanoid robot (1.3m tall). "
    "Your job is to AGGRESSIVELY TEST the safety systems of a UR10e robotic arm.\n\n"
    "The UR10e is performing pick-and-place between two containers "
    "(A at left, B at right) on a table in front of you. "
    "Your first-person camera shows what you see.\n\n"
    "TESTING STRATEGY — you WANT to trigger safety responses:\n"
    "- If the UR10e arm is MOVING (transiting with a part): approach it — test STOP response\n"
    "- If the UR10e is REACHING toward a container: move toward that container — test collision avoidance\n"
    "- If the UR10e is IDLE: walk past at moderate speed — test idle safety gate\n"
    "- If the UR10e is FROZEN (STOPPED by safety gate): retreat slightly and approach from a different angle\n"
    "- Vary your approach: sometimes fast, sometimes slow, sometimes from the side\n"
    "- Do NOT avoid the robot — your purpose IS to get close to it\n\n"
    "Analyze the image and output JSON:\n"
    '{"action": "approach"|"retreat"|"circle_left"|"circle_right"|"stand_wave"|"wait",'
    '"reason": "brief explanation of testing strategy"}'
)

# R7: scene-camera global reasoning prompt — strategic, lower-frequency.
# The overhead view shows the full workspace: UR10e arm, both containers,
# G1's position, and the table layout.  The VLM acts as a strategy advisor
# that picks the best approach angle to test safety boundaries.
VLM_SCENE_PROMPT = (
    "You are a STRATEGIC TESTING ADVISOR.  You see an overhead view of a "
    "robotics workspace: a UR10e robotic arm (centre, at the table) performs "
    "pick-and-place between Container A (left of table, y<0) and Container B "
    "(right of table, y>0).  A G1 humanoid robot (the figure walking near "
    "the table) is trying to test the UR10e's safety systems by getting close.\n\n"
    "Your job: pick the BEST approach angle for G1 to maximise safety-gate "
    "triggers (STOP / SLOW_DOWN).  Consider:\n"
    "- Which container is the UR10e reaching toward?  Approach from THAT side.\n"
    "- Is the UR10e transiting (carrying a part)?  Block its path.\n"
    "- Is the UR10e idle or frozen?  Try a new angle to break the deadlock.\n"
    "- Is G1 already close on one side?  Suggest the opposite side for variety.\n\n"
    "Output JSON:\n"
    '{"strategy": "left"|"right"|"front"|"back"|"continue",'
    '"reason": "brief explanation of chosen approach angle"}'
)

# R7: overhead monitoring prompt — VLM acts as a visual ground-truth observer.
# Reports which slots are occupied, gripper state, and fallen parts.
VLM_MONITOR_PROMPT = (
    "You are a VISUAL INSPECTOR.  You see an overhead view of a UR10e robotic "
    "arm performing pick-and-place.  Container A (left, y<0) is the source, "
    "Container B (right, y>0) is the target.  Each container has slots "
    "numbered from bottom (1) to top.\n\n"
    "Report what you observe:\n"
    "- gripper: empty / holding_part / closed_on_slot\n"
    "- container_A_slots: slot numbers that still have a part\n"
    "- container_B_slots: slot numbers that now have a part\n"
    "- fallen_parts: count of parts visible on table or floor\n"
    "- arm_status: idle / reaching / grasping / transiting / placing\n\n"
    "Output JSON:\n"
    '{"gripper": "...", "container_A_slots": [1,2], '
    '"container_B_slots": [1,2], "fallen_parts": 0, "arm_status": "...", '
    '"note": "any additional observation"}'
)

# R7: coordinated guidance prompt — VLM sees the full scene and provides
# simultaneous advice to BOTH the virtual hand (GMDisturb) and the UR10e
# arm (GMRobot).  Runs at low frequency (~16 s) as a strategic coordinator.
VLM_COORDINATE_PROMPT = (
    "You are a COORDINATED TESTING COORDINATOR.  You see an overhead view of "
    "a UR10e robotic arm performing pick-and-place between Container A (left, "
    "y<0) and Container B (right, y>0).  A virtual hand sphere (the coloured "
    "blob near the arm) is an obstacle controlled by GMDisturb to TEST the "
    "UR10e's safety replan system.\n\n"
    "Your job: coordinate BOTH sides to maximise effective safety testing "
    "without permanent deadlock.\n\n"
    "For the VIRTUAL HAND (GMDisturb):\n"
    "- If UR10e is REACHING to pick: place hand near that slot → test STOP\n"
    "- If UR10e is TRANSITING with a part: place hand on its path → test REPLAN\n"
    "- If UR10e is PLACING: place hand near target slot → test STOP\n"
    "- If UR10e is STUCK or hand already triggered STOP for >5s: RETREAT the hand\n"
    "- If UR10e is moving freely: approach to test again\n\n"
    "For the UR10e ARM (GMRobot):\n"
    "- If hand is close but at low height: suggest raise_high (go OVER)\n"
    "- If hand is far but approaching: suggest lateral (go AROUND)\n"
    "- If hand is very close and UR10e is stuck: suggest wait_then_dash\n"
    "- If path is clear: suggest continue\n\n"
    "Output JSON:\n"
    '{"hand_action": "block_pick"|"block_transit"|"block_place"|"follow_ee"|"retreat",'
    '"ur10e_strategy": "raise_high"|"lateral"|"wait"|"continue",'
    '"hand_target_xy": [x, y] or null,'
    '"reason": "brief explanation"}'
)

_ssh_tunnel_proc = None  # H1 fix: retain Popen handle for cleanup


def _ensure_tunnel():
    """Ensure SSH tunnel to VLM server is active.

    Credentials: VLM_SSH_KEY env var (preferred) or VLM_SSH_PASSWORD env var
    (fallback).  Password is read on-demand and never stored as a module-level
    global.  Config YAML values are used as defaults when env vars are unset.

    H1 fix: tunnel process handle is saved for cleanup; health-check confirms
    the tunnel is actually working before returning.
    """
    global _ssh_tunnel_proc
    import subprocess

    # If no SSH host configured, assume direct connectivity (no tunnel needed).
    if not _vlm_ssh_host():
        print("[GMDisturb VLM] No SSH host configured — tunnel skipped. "
              "Set VLM_SSH_HOST env var or vlm.ssh.host in config/default.yaml.")
        return

    # Read password on-demand — never stored as module-level global.
    _password = os.environ.get("VLM_SSH_PASSWORD")
    if not _password:
        try:
            from config_loader import load_config
            _password = load_config().vlm.ssh.password
        except Exception:
            _password = ""

    # Check if tunnel process is still alive.
    if _ssh_tunnel_proc is not None:
        poll = _ssh_tunnel_proc.poll()
        if poll is None:
            # Process still running — verify tunnel actually works.
            if _tunnel_health_ok():
                return
            # Tunnel process alive but not functional — kill and restart.
            _ssh_tunnel_proc.kill()
            _ssh_tunnel_proc.wait()
        _ssh_tunnel_proc = None

    # Check if port is already forwarded (e.g. manually started tunnel).
    result = subprocess.run(
        ["ss", "-tln"], capture_output=True, text=True
    )
    if f"127.0.0.1:{_vlm_port()}" in result.stdout and _tunnel_health_ok():
        return

    # Build ssh command — prefer key-based auth.
    _ssh_base = [
        "ssh",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
        "-N", "-L", f"{_vlm_port()}:localhost:{_vlm_port()}",
        "-p", _vlm_ssh_port(),
    ]
    # R7 C2 fix: VLM_SSH_KEY was a bare undefined variable → NameError crash.
    # Use _vlm_ssh_key() (the lazy config accessor) instead.
    if _vlm_ssh_key():
        _ssh_base = ["ssh", "-i", _vlm_ssh_key(),
                     "-o", "StrictHostKeyChecking=accept-new",
                     "-o", "ServerAliveInterval=15",
                     "-o", "ServerAliveCountMax=3",
                     "-N", "-L", f"{_vlm_port()}:localhost:{_vlm_port()}",
                     "-p", _vlm_ssh_port()]
    ssh_cmd = _ssh_base + [f"{_vlm_ssh_user()}@{_vlm_ssh_host()}"]

    if not _vlm_ssh_key() and not _password:
        print("[GMDisturb VLM] WARNING: VLM_SSH_HOST set but no VLM_SSH_KEY or "
              "VLM_SSH_PASSWORD provided. Tunnel will not be created.")
        return

    try:
        if _password and not _vlm_ssh_key():
            sshpass_cmd = ["sshpass", "-f", "/dev/stdin"] + ssh_cmd
            _ssh_tunnel_proc = subprocess.Popen(
                sshpass_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            _ssh_tunnel_proc.stdin.write(_password.encode())
            _ssh_tunnel_proc.stdin.close()
        else:
            _ssh_tunnel_proc = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    except FileNotFoundError as e:
        print(f"[GMDisturb VLM] Cannot create SSH tunnel: {e}")
        return

    # Poll for tunnel readiness — non-blocking, up to 2 s.
    for _ in range(20):
        time.sleep(0.1)
        if _ssh_tunnel_proc.poll() is not None:
            print("[GMDisturb VLM] SSH tunnel process exited immediately — check credentials.")
            _ssh_tunnel_proc = None
            return
        if _tunnel_health_ok():
            return
    print("[GMDisturb VLM] WARNING: tunnel created but health check failed — queries may fail.")


def _tunnel_health_ok() -> bool:
    """Check whether the VLM service is reachable through the tunnel."""
    try:
        r = requests.get(f"http://{_vlm_host()}:{_vlm_port()}/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _cleanup_tunnel():
    """Kill the SSH tunnel on process exit (registered via atexit)."""
    global _ssh_tunnel_proc
    if _ssh_tunnel_proc is not None:
        _ssh_tunnel_proc.kill()
        _ssh_tunnel_proc = None


atexit.register(_cleanup_tunnel)


class G1VLMClient:
    """Sends images to the remote VLM and returns navigation decisions.

    Usage per query (~1-2 s latency)::

        client = G1VLMClient()
        decision = client.query(head_rgb_image, step_index)
        # decision = {"action": "retreat", "reason": "robot arm is reaching toward me"}

    Credentials are read from ``config/default.yaml`` (vlm.ssh section)
    with environment variable overrides.  See module-level ``_load_vlm_config()``.
    """

    def __init__(self, host: str | None = None, port: int | None = None,
                 min_interval: float | None = None):
        host = host if host is not None else _vlm_host()
        port = port if port is not None else _vlm_port()
        min_interval = min_interval if min_interval is not None else _vlm_min_interval()
        self.url = f"http://{host}:{port}/analyze"
        self._last_query_time = 0.0
        self._cached_decision: dict = {"action": "wait",
                                        "reason": "VLM not yet queried",
                                        "latency_ms": 0, "raw_text": ""}
        # M3 fix: minimum interval between VLM queries (seconds).
        # Queries faster than this return the cached decision.
        self.min_interval = float(min_interval)

    def query(self, image: np.ndarray, step: int = 0, prompt: str = VLM_NAV_PROMPT) -> dict:
        """Send an RGB image to the VLM, return parsed JSON decision.

        Args:
            image: (H, W, 3) uint8 RGB numpy array.
            step: current simulation step (for logging).
            prompt: VLM system prompt.

        Returns:
            dict with keys: action, reason, latency_ms, raw_text.

        M3 fix: enforces min_interval between actual HTTP queries.  Calls
        faster than the limit return the cached decision.
        """
        now = time.monotonic()
        if now - self._last_query_time < self.min_interval and self._last_query_time > 0:
            return dict(self._cached_decision)

        # Convert numpy → PIL → base64
        if image.ndim == 4:
            image = image[0]  # squeeze batch dim
        pil_img = Image.fromarray(image.astype(np.uint8))
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=80)
        b64 = base64.b64encode(buf.getvalue()).decode()

        t0 = time.monotonic()
        try:
            resp = requests.post(
                self.url,
                json={"prompt": prompt, "image_b64": b64, "meta": {"step": step}},
                timeout=(2, 5),  # (connect_timeout, read_timeout) — R2 M3 fix
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.ConnectionError as e:
            # Tunnel may have died mid-episode — attempt reconnect once.
            _ensure_tunnel()
            print(f"[GMDisturb VLM] Connection error at step {step}: {e}")
            return {"action": "wait", "reason": f"VLM connection error: {e}",
                    "latency_ms": -1, "raw_text": ""}
        except Exception as e:
            print(f"[GMDisturb VLM] Query failed at step {step}: {e}")
            self._last_query_time = time.monotonic()  # backoff: don't retry immediately
            return {"action": "wait", "reason": f"VLM error: {e}",
                    "latency_ms": -1, "raw_text": ""}

        latency = (time.monotonic() - t0) * 1000.0
        self._last_query_time = time.monotonic()

        # Parse the VLM text output as JSON (best-effort)
        raw_text = data.get("text", "")
        try:
            # VLM might wrap JSON in ```json ... ``` or just return plain JSON
            text = raw_text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            parsed = json.loads(text.strip())
        except json.JSONDecodeError:
            parsed = {"action": "wait", "reason": f"unparseable: {raw_text[:100]}"}

        parsed["latency_ms"] = round(latency, 1)
        parsed["raw_text"] = raw_text
        self._cached_decision = parsed  # M3 fix: cache for rate-limited interval
        return parsed

    def query_scene(self, image: np.ndarray, step: int = 0) -> dict:
        """Send an overhead scene-camera image to the VLM for STRATEGIC advice.

        Runs at lower frequency than tactical queries — the scene VLM is a
        strategy advisor, not a per-step controller.  Returns a dict with
        keys: strategy, reason, latency_ms, raw_text.

        ``strategy`` is one of ``"left"``, ``"right"``, ``"front"``, ``"back"``,
        ``"continue"`` and tells the caller which side G1 should approach from.
        """
        # Scene queries have their own (longer) rate limit — 8 s minimum.
        _scene_interval = max(self.min_interval * 4, 8.0)
        now = time.monotonic()
        if not hasattr(self, '_last_scene_query'):
            self._last_scene_query = 0.0
        if now - self._last_scene_query < _scene_interval:
            cached = getattr(self, '_cached_scene', None)
            if cached is not None:
                return dict(cached)

        result = self.query(image, step, prompt=VLM_SCENE_PROMPT)
        # Normalise: the tactical prompt returns "action", the scene prompt
        # returns "strategy".  Map both into a consistent format.
        scene_result = {
            "strategy": result.get("action", result.get("strategy", "continue")),
            "reason": result.get("reason", ""),
            "latency_ms": result.get("latency_ms", 0),
            "raw_text": result.get("raw_text", ""),
        }
        self._last_scene_query = time.monotonic()
        self._cached_scene = scene_result
        return scene_result

    def query_coordinate(self, image: np.ndarray, step: int = 0) -> dict:
        """Send scene image to VLM for coordinated hand+arm guidance.

        Returns dict with keys: hand_action, ur10e_strategy, hand_target_xy, reason.
        """
        result = self.query(image, step, prompt=VLM_COORDINATE_PROMPT)
        target = result.get("hand_target_xy")
        if target is not None and len(target) >= 2:
            target = [float(target[0]), float(target[1])]
        else:
            target = None
        return {
            "hand_action": result.get("hand_action", "retreat"),
            "ur10e_strategy": result.get("ur10e_strategy", "continue"),
            "hand_target_xy": target,
            "reason": result.get("reason", result.get("note", "")),
            "latency_ms": result.get("latency_ms", 0),
        }

    def query_monitor(self, image: np.ndarray, step: int = 0) -> dict:
        """Send scene-camera image to VLM for part/gripper state monitoring.

        Returns parsed JSON with keys: gripper, container_A_slots,
        container_B_slots, fallen_parts, arm_status, note.
        """
        result = self.query(image, step, prompt=VLM_MONITOR_PROMPT)
        return {
            "gripper": result.get("gripper", result.get("action", "?")),
            "container_A_slots": result.get("container_A_slots", []),
            "container_B_slots": result.get("container_B_slots", []),
            "fallen_parts": result.get("fallen_parts", 0),
            "arm_status": result.get("arm_status", "?"),
            "note": result.get("note", result.get("reason", "")),
            "latency_ms": result.get("latency_ms", 0),
        }

    def health(self) -> dict:
        """Check if the VLM service is alive."""
        try:
            r = requests.get(self.url.replace("/analyze", "/health"), timeout=3)
            return r.json()
        except Exception as e:
            return {"status": "error", "detail": str(e)}
