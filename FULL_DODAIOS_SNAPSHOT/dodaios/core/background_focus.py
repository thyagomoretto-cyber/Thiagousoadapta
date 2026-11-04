"""Mantem o servico sem janela fora do Dock e sem tirar o foco de outros apps."""
from __future__ import annotations

import sys


def stay_in_background() -> None:
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyProhibited
    except ImportError:
        return
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyProhibited)
