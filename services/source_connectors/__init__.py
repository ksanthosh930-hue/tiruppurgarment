"""
Website Source Connectors package for DigiGarment Tiruppur Jobs platform.
"""

from services.source_connectors.base import BaseSourceConnector
from services.source_connectors.sankar_jobs import SankarJobsConnector
from services.source_connectors.cotton_jobs import CottonJobsConnector
from services.source_connectors.registry import ConnectorRegistry, connector_registry

__all__ = [
    "BaseSourceConnector",
    "SankarJobsConnector",
    "CottonJobsConnector",
    "ConnectorRegistry",
    "connector_registry"
]
