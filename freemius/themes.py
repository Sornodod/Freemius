"""Палитры тем + сборка QSS."""

THEMES = {
    "dark": {
        "name": "Тёмная",
        "bg":         "#101418",
        "bg_alt":     "#14181d",
        "panel":      "#1b2026",
        "panel_hov":  "#232a32",
        "border":     "#2b3138",
        "border_hov": "#3f4a55",
        "text":       "#d8dee9",
        "text_dim":   "#7f8a99",
        "accent":     "#2d6cdf",
        "accent_hov": "#3a7ce8",
        "accent_prs": "#245bbd",
        "input_bg":   "#14181d",
        "tab_bg":     "#1b2026",
        "tab_fg":     "#a6adba",
    },
    "light": {
        "name": "Светлая",
        "bg":         "#f5f5f7",
        "bg_alt":     "#ffffff",
        "panel":      "#ffffff",
        "panel_hov":  "#eef0f3",
        "border":     "#d6d9de",
        "border_hov": "#b8bcc3",
        "text":       "#1f2328",
        "text_dim":   "#6a7380",
        "accent":     "#2d6cdf",
        "accent_hov": "#3a7ce8",
        "accent_prs": "#245bbd",
        "input_bg":   "#ffffff",
        "tab_bg":     "#e6e8ec",
        "tab_fg":     "#4a515a",
    },
    "navy": {
        "name": "Тёмно-синяя",
        "bg":         "#0a1420",
        "bg_alt":     "#0e1c2c",
        "panel":      "#12253a",
        "panel_hov":  "#18324c",
        "border":     "#1e3a55",
        "border_hov": "#2b5074",
        "text":       "#d8e6f2",
        "text_dim":   "#7a94ad",
        "accent":     "#3a8eef",
        "accent_hov": "#4f9cf5",
        "accent_prs": "#2b74c9",
        "input_bg":   "#0e1c2c",
        "tab_bg":     "#12253a",
        "tab_fg":     "#8aa4bc",
    },
    "forest": {
        "name": "Тёмно-зелёная",
        "bg":         "#0f1a12",
        "bg_alt":     "#12201a",
        "panel":      "#182a1f",
        "panel_hov":  "#1f3528",
        "border":     "#264a35",
        "border_hov": "#356b4d",
        "text":       "#d4e8d8",
        "text_dim":   "#7aa088",
        "accent":     "#3fa64a",
        "accent_hov": "#4fbf5a",
        "accent_prs": "#328a3c",
        "input_bg":   "#12201a",
        "tab_bg":     "#182a1f",
        "tab_fg":     "#8ab49a",
    },
}

DEFAULT_THEME = "dark"


def get_theme(key):
    return THEMES.get(key) or THEMES[DEFAULT_THEME]


def build_stylesheet(t: dict) -> str:
    """QSS для всего приложения по палитре темы."""
    return f"""
    QMainWindow, QWidget {{
        background-color: {t['bg']};
        color: {t['text']};
    }}
    QTabWidget::pane {{ border: 0; background: {t['bg']}; }}
    QTabBar::tab {{
        background: {t['tab_bg']}; color: {t['tab_fg']};
        padding: 6px 12px; margin-right: 2px;
        border-top-left-radius: 4px; border-top-right-radius: 4px;
    }}
    QTabBar::tab:selected {{ background: {t['bg']}; color: {t['text']}; }}

    QLineEdit, QSpinBox, QComboBox {{
        background: {t['input_bg']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 4px;
        padding: 4px 6px;
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border: 1px solid {t['accent']};
    }}

    QPushButton {{
        background: {t['panel']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 6px;
        padding: 6px 12px;
    }}
    QPushButton:hover {{ background: {t['panel_hov']}; border-color: {t['border_hov']}; }}
    QPushButton:pressed {{ background: {t['accent_prs']}; color: white; }}

    QListWidget {{
        background: {t['bg_alt']}; color: {t['text']};
        border: 1px solid {t['border']};
    }}
    QListWidget::item:selected {{ background: {t['accent']}; color: white; }}

    QScrollArea {{ background: transparent; }}

    QMenu {{
        background: {t['panel']}; color: {t['text']};
        border: 1px solid {t['border']};
    }}
    QMenu::item:selected {{ background: {t['accent']}; color: white; }}

    QLabel {{ background: transparent; color: {t['text']}; }}

    QCheckBox {{ color: {t['text']}; }}

    QProgressBar {{
        background: {t['input_bg']}; border: 1px solid {t['border']};
        border-radius: 4px; text-align: center; color: {t['text']};
    }}
    QProgressBar::chunk {{ background: {t['accent']}; border-radius: 3px; }}
    """
