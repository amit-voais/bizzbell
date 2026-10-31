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
}
ALIASES = {"tick": "check", "done": "check", "cta": "arrow", "go": "arrow", "next": "arrow", "rating": "star",
           "offer": "gift", "box": "gift", "time": "clock", "hours": "clock", "call": "phone", "app": "phone",
           "location": "pin", "map": "pin", "new": "spark", "magic": "spark", "love": "heart", "shop": "cart",
           "buy": "cart", "fast": "bolt", "speed": "bolt", "message": "chat", "whatsapp": "chat", "price": "tag",
           "sale": "tag", "fresh": "leaf", "natural": "leaf"}


def svg(name, size=48, stroke=1.8, cls="bb-icon"):
    """Inline SVG for an icon name (aliases allowed); '' for an unknown or empty name."""
    key = str(name or "").strip().lower()
    key = ALIASES.get(key, key)
    body = PATHS.get(key)
    if not body:
        return ""
    return ('<svg class="%s" width="%d" height="%d" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="%s" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">%s</svg>'
            % (cls, size, size, stroke, body))
