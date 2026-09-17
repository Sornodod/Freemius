"""Палитры тем."""

THEMES = {
    "dark": {
        "name": "Тёмная",
        "bg":        "#101418",
        "bg_alt":    "#14181d",
        "panel":     "#1b2026",
        "panel_hov": "#232a32",
        "border":    "#2b3138",
        "border_hov":"#3f4a55",
        "text":      "#d8dee9",
        "text_dim":  "#7f8a99",
        "accent":    "#2d6cdf",
        "accent_hov":"#3a7ce8",
        "accent_prs":"#245bbd",
        "input_bg":  "#14181d",
        "tab_bg":    "#1b2026",
        "tab_fg":    "#a6adba",
    },
}


DEFAULT_THEME = "dark"


def get_theme(key):
    return THEMES.get(key) or THEMES[DEFAULT_THEME]
