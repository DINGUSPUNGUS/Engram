"""Application layer: use-case services (commands and queries) and their DTOs.

Interface layers (API, CLI, MCP) call these services and nothing deeper. Services
orchestrate: load aggregate → decide → wrap payloads in envelopes → append →
publish. They contain no storage details and no transport details.
"""
