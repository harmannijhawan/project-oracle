from .fallback import detect_regions
from .hit_test import Candidate, ElementIndex
from .model import INTERACTIVE_TYPES, Rect, ScreenSnapshot, UIElement, WindowInfo
from .provider import (CachedProvider, ScreenProvider, StaticScreenProvider, UIAutomationProvider,
                       default_provider)

__all__ = ["INTERACTIVE_TYPES", "Candidate", "CachedProvider", "ElementIndex", "Rect", "ScreenProvider",
           "ScreenSnapshot", "StaticScreenProvider", "UIAutomationProvider", "UIElement", "WindowInfo",
           "default_provider", "detect_regions"]
