from __future__ import annotations


def powered_by_payload() -> dict:
    return {
        "name": "EtnaMonitor",
        "label": "Powered by EtnaMonitor",
        "url": "https://etnamonitor.it",
    }


def attribution_snippet() -> dict:
    return {
        "html": (
            "<a href=\"https://etnamonitor.it\" target=\"_blank\" "
            "rel=\"noopener\" class=\"em-powered\">Powered by EtnaMonitor</a>"
        ),
        "text": "Powered by EtnaMonitor",
        "url": "https://etnamonitor.it",
    }
