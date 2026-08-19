"""
Section modules for the Client Review Pack / Global Client Summary PDF.

Every module here follows the same shape:
    - one or more Pydantic models describing its input data, decoupled from any
      particular source system (see the package docstring for why),
    - a `build_<name>_section(data) -> Section` function.

`Section` and the branding/table helpers live in `api.lib.pdf_builder` — import
from there rather than duplicating colours, fonts, or table chrome locally.
"""
from __future__ import annotations

from reportlab.lib.pagesizes import A3, A4, landscape

from api.lib.pdf_builder import Section

PORTRAIT_A4 = A4
LANDSCAPE_A4 = landscape(A4)
LANDSCAPE_A3 = landscape(A3)

__all__ = ["Section", "PORTRAIT_A4", "LANDSCAPE_A4", "LANDSCAPE_A3"]
