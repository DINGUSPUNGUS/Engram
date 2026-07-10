"""engram-core: the domain model and application services.

Pure by construction — this package imports only ``engram_events`` and the standard
library. No SQLite, no git, no HTTP, no framework. Adapters implement the ports
defined in :mod:`engram_core.domain.ports`; interface layers call the services in
:mod:`engram_core.application`.
"""
