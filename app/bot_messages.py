"""Centralized Telegram bot message templates for EtnaMonitor."""

from __future__ import annotations

def _cta_dashboard() -> str:
    return "Vai su EtnaMonitor → Dashboard"


def _premium_note() -> str:
    return "Premium con donazione PayPal min €9,99 (inserisci email registrazione)."


def _service_note() -> str:
    return "Servizio informativo/didattico."


def start_new_user() -> str:
    return "\n".join(
        [
            "👋 Benvenuto su EtnaMonitor",
            _service_note(),
            "Collega il tuo account per ricevere gli alert Telegram.",
            "Apri la Dashboard e premi “Collega Telegram”.",
            _cta_dashboard(),
        ]
    )


def start_existing_user(is_premium: bool, has_free_trial: bool) -> str:
    if is_premium:
        return "\n".join(
            [
                "✅ Telegram collegato",
                _service_note(),
                "Gli alert sono attivi sulla tua soglia personalizzata.",
                _cta_dashboard(),
            ]
        )
    if has_free_trial:
        return "\n".join(
            [
                "✅ Telegram collegato",
                _service_note(),
                "Hai 1 alert di prova disponibile.",
                _premium_note(),
                _cta_dashboard(),
            ]
        )
    return "\n".join(
        [
            "✅ Telegram collegato",
            _service_note(),
            "La prova gratuita è già stata usata.",
            _premium_note(),
            _cta_dashboard(),
        ]
    )


def link_success() -> str:
    return "\n".join(
        [
            "✅ Telegram collegato",
            _service_note(),
            "Riceverai alert in base alla tua soglia.",
            _cta_dashboard(),
        ]
    )


def link_invalid() -> str:
    return "\n".join(
        [
            "⚠️ Link non valido",
            _service_note(),
            "Rigenera il collegamento dalla Dashboard.",
            _cta_dashboard(),
        ]
    )


def link_already_used() -> str:
    return "\n".join(
        [
            "⚠️ Link già usato",
            _service_note(),
            "Genera un nuovo link dalla Dashboard.",
            _cta_dashboard(),
        ]
    )


def link_expired() -> str:
    return "\n".join(
        [
            "⚠️ Link scaduto",
            _service_note(),
            "Rigenera il collegamento dalla Dashboard.",
            _cta_dashboard(),
        ]
    )


def link_account_missing() -> str:
    return "\n".join(
        [
            "⚠️ Account non trovato",
            _service_note(),
            "Riprova dal pulsante in Dashboard.",
            _cta_dashboard(),
        ]
    )


def link_conflict_existing_account() -> str:
    return "\n".join(
        [
            "⚠️ Telegram già collegato",
            _service_note(),
            "Questo account è associato a un altro profilo.",
            _cta_dashboard(),
        ]
    )


def link_conflict_other_chat() -> str:
    return "\n".join(
        [
            "⚠️ Account già collegato",
            _service_note(),
            "Il tuo profilo EtnaMonitor è legato a un altro Telegram.",
            _cta_dashboard(),
        ]
    )


def link_error() -> str:
    return "\n".join(
        [
            "❌ Errore di collegamento",
            _service_note(),
            "Riprova dalla Dashboard tra qualche minuto.",
            _cta_dashboard(),
        ]
    )


def help_text() -> str:
    return "\n".join(
        [
            "ℹ️ Guida rapida EtnaBot",
            _service_note(),
            "Usa /start per collegare il profilo o verificare lo stato.",
            "Per modificare la soglia vai in Dashboard.",
            _cta_dashboard(),
        ]
    )


def premium_alert(current_value: float, peak_value: float, threshold: float) -> str:
    return "\n".join(
        [
            "🌋 Allerta Etna",
            "Tremore oltre soglia personalizzata (servizio informativo/didattico).",
            f"Valore attuale: {current_value:.2f} mV",
            f"Picco: {peak_value:.2f} mV · Soglia: {threshold:.2f} mV",
            _cta_dashboard(),
        ]
    )


def free_trial_alert(current_value: float, peak_value: float, threshold: float) -> str:
    return "\n".join(
        [
            "🌋 Alert di prova",
            "Tremore oltre soglia (servizio informativo/didattico).",
            f"Valore attuale: {current_value:.2f} mV · Picco: {peak_value:.2f} mV",
            f"Soglia: {threshold:.2f} mV · {_premium_note()}",
            _cta_dashboard(),
        ]
    )


def upsell_message() -> str:
    return "\n".join(
        [
            "⭐ Premium EtnaMonitor",
            _service_note(),
            "Attiva Premium con donazione PayPal min €9,99.",
            "Nella donazione inserisci la tua email di registrazione.",
            _cta_dashboard(),
        ]
    )
