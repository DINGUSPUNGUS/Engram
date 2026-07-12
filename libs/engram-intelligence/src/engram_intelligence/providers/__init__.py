"""Provider adapters. The ONLY place vendor SDKs may be imported (ADR-0012).

All stubs until roadmap phase 8; each implementation adds its SDK as an optional
dependency extra and translates SDK exceptions to EngramError before they escape.
"""
