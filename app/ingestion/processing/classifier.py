"""Adapter exposing profile registry through the application classifier port."""
from .profiles import ProfileRegistry
from ..domain.models import ParsedDocument, DocumentSource


class RegistryClassifier:
    def __init__(self, registry: ProfileRegistry):
        self.registry = registry

    def classify(self, document: ParsedDocument, source: DocumentSource) -> str:
        return self.registry.classify(document).kind
