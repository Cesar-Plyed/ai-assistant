# ADR 0002 — One global stylesheet with tokens
Status: accepted. Six per-widget copies of the palette drifted apart and made Light mode
impossible. `ui/theme.py` owns tokens and the stylesheet; widgets opt in via properties.
