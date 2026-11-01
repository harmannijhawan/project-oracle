"""Computer-vision fallback for apps that expose little accessibility data.

Finds rectangular, button-like regions in a screenshot using edges + contours. These are returned as
``Region`` elements with ``source='vision'``: they carry no names, so the brain trusts them less.
The screenshot is processed in memory only.
"""

from __future__ import annotations

from .model import Rect, UIElement


def detect_regions(image_bgr, offset: tuple[int, int] = (0, 0), min_w: int = 24, min_h: int = 14,
                   max_frac: float = 0.5, limit: int = 120) -> list[UIElement]:  # type: ignore[no-untyped-def]
    import cv2  # local import: optional dependency

    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 40, 120)
    edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out: list[UIElement] = []
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw < min_w or bh < min_h or bw * bh > max_frac * w * h or bw / bh > 25:
            continue
        if cv2.contourArea(c) < 0.5 * bw * bh and len(cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)) != 4:
            continue  # not rectangle-like
        ox, oy = offset
        out.append(UIElement(f"v:{x}:{y}", "", "Region", Rect(ox + x, oy + y, ox + x + bw, oy + y + bh), source="vision"))
    out.sort(key=lambda e: e.rect.area)
    return out[:limit]
