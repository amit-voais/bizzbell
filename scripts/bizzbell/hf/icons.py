"""Built-in line icons for graphic shots, drawn as SVG on a 24 x 24 grid (stroke = currentColor). Never emoji."""

PATHS = {
    "check": '<path d="M5 12.5l4.2 4.2L19 7"/>',
    "arrow": '<path d="M4 12h15"/><path d="M13 6l6 6-6 6"/>',
    "star": '<path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.9 6.8 19.6l1-5.8-4.3-4.1 5.9-.8z"/>',
    "gift": '<rect x="3.5" y="8.5" width="17" height="4" rx="1"/><path d="M5 12.5v8h14v-8"/>'
            '<path d="M12 8.5v12"/><path d="M12 8.5c-1.5-3.5-5.5-4-5.5-1.5S10 8.5 12 8.5z"/>'
            '<path d="M12 8.5c1.5-3.5 5.5-4 5.5-1.5S14 8.5 12 8.5z"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "phone": '<rect x="7" y="2.5" width="10" height="19" rx="2.2"/><path d="M10.5 18.5h3"/>',
    "pin": '<path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0113 0c0 5.4-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.4"/>',
    "spark": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4"/><path d="M12 8.5l1.2 2.3 2.3 1.2-2.3 1.2L12 15.5l-1.2-2.3'
             '-2.3-1.2 2.3-1.2z"/>',
    "heart": '<path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0112 7.4 4.3 4.3 0 0119.5 10c0 5.4-7.5 10-7.5 10z"/>',
    "cart": '<path d="M3 4h2.5l2.2 10.5h10.6L20.5 7H7"/><circle cx="9.5" cy="19" r="1.4"/><circle cx="17" cy="19" '
            'r="1.4"/>',
    "bolt": '<path d="M13 2.5L5 13.5h6l-1 8 8-11h-6z"/>',
    "chat": '<path d="M4 5.5h16v10H9.5L5 19.5v-4H4z"/><path d="M8 10.5h8"/>',
    "tag": '<path d="M3.5 12.2V4.5a1 1 0 011-1h7.7l8.3 8.3-8.7 8.7z"/><circle cx="8" cy="8" r="1.4"/>',
    "leaf": '<path d="M5 19c0-8 5-13 14-14 0 9-5 14-13 14z"/><path d="M5 19l7-7"/>',
    "play": '<path d="M8 5l11 7-11 7z"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M11 12l8.5-8.5"/><path d="M16 7l3 3"/>',
    "film": '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M8 4.5v15M16 4.5v15M3.5 12h17"/>'
            '<path d="M3.5 8.2H8M3.5 15.8H8M16 8.2h4.5M16 15.8h4.5"/>',
    "layers": '<path d="M12 3.5l8.5 4.5-8.5 4.5L3.5 8z"/><path d="M3.5 12l8.5 4.5 8.5-4.5"/>'
              '<path d="M3.5 16l8.5 4.5 8.5-4.5"/>',
    "shield": '<path d="M12 3l7.5 2.8v5.7c0 4.6-3.1 7.7-7.5 9.5-4.4-1.8-7.5-4.9-7.5-9.5V5.8z"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0013 0"/>'
           '<path d="M12 18v3"/>',
    "camera": '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8.5 7l1.5-3h4l1.5 3"/>'
              '<circle cx="12" cy="13.5" r="3.5"/>',
    "music": '<path d="M9 18V5.5l10-2V16"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c1-4 4-6 7.5-6s6.5 2 7.5 6"/>',
    "code": '<path d="M8.5 7L3.5 12l5 5"/><path d="M15.5 7l5 5-5 5"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5l5 5"/>',
    "chart": '<path d="M4 20.5h16"/><path d="M7 16.5v-5M12 16.5v-10M17 16.5v-7"/>',
    "mail": '<rect x="3" y="5.5" width="18" height="13" rx="1.5"/><path d="M3.5 7l8.5 6.5L20.5 7"/>',
}
ALIASES = {"tick": "check", "done": "check", "cta": "arrow", "go": "arrow", "next": "arrow", "rating": "star",
           "offer": "gift", "box": "gift", "time": "clock", "hours": "clock", "call": "phone", "app": "phone",
           "location": "pin", "map": "pin", "new": "spark", "magic": "spark", "love": "heart", "shop": "cart",
           "buy": "cart", "fast": "bolt", "speed": "bolt", "message": "chat", "whatsapp": "chat", "price": "tag",
           "sale": "tag", "fresh": "leaf", "natural": "leaf", "video": "film", "safe": "shield", "secure": "shield",
           "stack": "layers", "voice": "mic", "person": "user", "photo": "camera", "email": "mail", "find": "search"}


def _key(name):
    key = str(name or "").strip().lower()
    return ALIASES.get(key, key)


def unknown(names):
    """The names, in order, that have no icon. An empty name is fine: it means no icon was asked for."""
    return [str(n) for n in names if _key(n) and _key(n) not in PATHS]


def svg(name, size=48, stroke=1.8, cls="bb-icon"):
    """Inline SVG for an icon name (aliases allowed); '' for an unknown or empty name."""
    body = PATHS.get(_key(name))
    if not body:
        return ""
    return ('<svg class="%s" width="%d" height="%d" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="%s" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">%s</svg>'
            % (cls, size, size, stroke, body))
