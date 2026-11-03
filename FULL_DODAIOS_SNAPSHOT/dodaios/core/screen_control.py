"""Ve a tela do Mac e usa mouse e teclado no ensino ao vivo, sem passar pelo modelo.

Le a tela com o OCR nativo do macOS e clica pelo texto, nunca por coordenada
guardada. Ignora as janelas do proprio DodaiOS, para nao clicar no historico do
ensino. Ao observar o dono, registra so os cliques: teclas nao sao gravadas,
porque poderiam conter senhas.
"""
from __future__ import annotations

import os
import queue
import subprocess
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Final

_SELF_WINDOW: Final[str] = "DodaiOS"
_NEAR_POINTS: Final[float] = 70.0
_KEY_CODES: Final[dict[str, int]] = {
    "enter": 36, "tab": 48, "esc": 53, "espaco": 49, "apagar": 51,
    "baixo": 125, "cima": 126, "esquerda": 123, "direita": 124,
}
_CMD_V_KEY: Final[int] = 9
_SCROLL_LINES: Final[int] = 8
_MAX_STEP_LABEL: Final[int] = 80


@dataclass(frozen=True, slots=True)
class ScreenText:
    text: str
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2


def fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    return " ".join("".join(c for c in plain if not unicodedata.combining(c)).lower().split())


def find_text(target: str, items: list[ScreenText]) -> tuple[float, float] | None:
    """O ponto do texto pedido: igual primeiro, depois dentro de uma linha maior."""
    wanted = fold(target)
    if not wanted:
        return None
    exact = [item for item in items if fold(item.text) == wanted]
    if exact:
        return min(exact, key=lambda item: item.y).center
    partial = [item for item in items if wanted in fold(item.text)]
    if not partial:
        return None
    item = min(partial, key=lambda entry: len(entry.text))
    line = fold(item.text)
    middle = (line.index(wanted) + len(wanted) / 2) / max(len(line), 1)
    return item.x + item.width * middle, item.y + item.height / 2


def nearest_text(x: float, y: float, items: list[ScreenText]) -> str:
    """O texto sob o clique, ou o mais proximo dele."""
    best, distance = "", _NEAR_POINTS
    for item in items:
        inside = item.x <= x <= item.x + item.width and item.y <= y <= item.y + item.height
        cx, cy = item.center
        gap = 0.0 if inside else ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5
        if gap < distance:
            best, distance = item.text, gap
    return best[:_MAX_STEP_LABEL]


def _own_windows() -> list[tuple[float, float, float, float]]:
    import Quartz

    found = []
    windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
    for window in windows or ():
        if window.get("kCGWindowOwnerName") == _SELF_WINDOW and window.get("kCGWindowLayer") == 0:
            box = window["kCGWindowBounds"]
            found.append((box["X"], box["Y"], box["Width"], box["Height"]))
    return found


def read_screen() -> list[ScreenText]:
    """Todo texto visivel na tela principal, fora das janelas do DodaiOS."""
    import Quartz
    import Vision
    from Foundation import NSURL

    handle, path = tempfile.mkstemp(suffix=".png")
    os.close(handle)
    try:
        subprocess.run(["screencapture", "-x", "-m", path], check=True, timeout=10)
        url = NSURL.fileURLWithPath_(path)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLanguages_(["pt-BR", "en-US"])
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, {})
        handler.performRequests_error_([request], None)
        results = request.results() or []
    finally:
        os.unlink(path)
    bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    width, height = bounds.size.width, bounds.size.height
    own = _own_windows()
    items = []
    for result in results:
        candidates = result.topCandidates_(1)
        if not candidates:
            continue
        box = result.boundingBox()
        item = ScreenText(
            str(candidates[0].string()),
            box.origin.x * width,
            (1 - box.origin.y - box.size.height) * height,
            box.size.width * width,
            box.size.height * height,
        )
        cx, cy = item.center
        if not any(x <= cx <= x + w and y <= cy <= y + h for x, y, w, h in own):
            items.append(item)
    return items


def mouse_position() -> tuple[float, float]:
    import Quartz

    point = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return point.x, point.y


def click_at(x: float, y: float) -> None:
    import Quartz

    for kind in (Quartz.kCGEventMouseMoved, Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        event = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        time.sleep(0.04)


def press_key(name: str, *, command: bool = False, code: int | None = None) -> None:
    import Quartz

    key = _KEY_CODES[name] if code is None else code
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(None, key, down)
        if command:
            Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        time.sleep(0.02)


def type_text(text: str) -> None:
    """Cola o texto, que preserva acentos, e devolve a area de transferencia."""
    env = {**os.environ, "LANG": "pt_BR.UTF-8"}
    before = subprocess.run(["pbpaste"], capture_output=True, env=env).stdout
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True, env=env)
    press_key("", command=True, code=_CMD_V_KEY)
    time.sleep(0.25)
    subprocess.run(["pbcopy"], input=before, check=True, env=env)


def scroll(direction: str) -> None:
    import Quartz

    amount = _SCROLL_LINES if direction == "cima" else -_SCROLL_LINES
    event = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, amount)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def permissions() -> dict[str, Any]:
    """O que o macOS liberou para este processo."""
    import Quartz

    try:
        import ApplicationServices

        controls = bool(ApplicationServices.AXIsProcessTrusted())
    except ImportError:
        controls = False
    try:
        seen = len(read_screen())
    except Exception:  # noqa: BLE001 — sem permissao a captura pode falhar de varias formas
        seen = 0
    return {"controle": controls, "textos_na_tela": seen, "tela": seen > 0, "tela_cheia": bool(Quartz.CGMainDisplayID())}


class ClickObserver:
    """Aprende olhando: anota em que o dono clicou enquanto o ensino esta aberto."""

    def __init__(self) -> None:
        self._steps: list[str] = []
        self._clicks: queue.Queue[tuple[float, float] | None] = queue.Queue()
        self._listener: Any = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._listener is not None:
                return
            from pynput import mouse

            self._steps = []

            def on_click(x: float, y: float, _button: Any, pressed: bool) -> None:
                if pressed:
                    self._clicks.put((x, y))

            self._listener = mouse.Listener(on_click=on_click)
            self._listener.start()
            threading.Thread(target=self._worker, name="ensino-observador", daemon=True).start()

    def _worker(self) -> None:
        while (click := self._clicks.get()) is not None:
            try:
                label = nearest_text(*click, read_screen())
            except Exception:  # noqa: BLE001 — um clique perdido nao para o ensino
                continue
            if label:
                self._steps.append(f'Clicar em "{label}"')

    def steps_after(self, seen: int) -> list[str]:
        return self._steps[seen:]

    def stop(self) -> None:
        with self._lock:
            if self._listener is not None:
                self._listener.stop()
                self._listener = None
                self._clicks.put(None)


OBSERVER: Final[ClickObserver] = ClickObserver()
