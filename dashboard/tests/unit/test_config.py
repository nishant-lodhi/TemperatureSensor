"""Tests for app.config — theme, thresholds, WiFi SVG icons."""

from app import config as cfg


def test_colors_has_required_keys():
    required = ["bg", "card", "card_border", "text", "text_muted",
                 "primary", "success", "warning", "danger", "critical"]
    for key in required:
        assert key in cfg.COLORS, f"Missing COLORS['{key}']"


def test_temperature_thresholds_ordered():
    assert cfg.TEMP_CRITICAL_LOW < cfg.TEMP_LOW < cfg.TEMP_HIGH < cfg.TEMP_CRITICAL_HIGH


def test_card_style_has_required_properties():
    assert "backgroundColor" in cfg.CARD_STYLE
    assert "borderRadius" in cfg.CARD_STYLE


def test_wifi_svg_icons_are_data_uris():
    for label in ("Strong", "Good", "Weak", "No Signal"):
        assert label in cfg.SIGNAL_ICONS, f"Missing SIGNAL_ICONS['{label}']"
        assert cfg.SIGNAL_ICONS[label].startswith("data:image/svg+xml;base64,")


def test_hover_label_has_required_keys():
    assert "bgcolor" in cfg.HOVER_LABEL
    assert "font" in cfg.HOVER_LABEL


def test_severity_labels_and_colors_match():
    for sev in cfg.SEVERITY_LABELS:
        assert sev in cfg.SEVERITY_COLORS, f"Severity '{sev}' in LABELS but not COLORS"
