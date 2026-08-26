from app.ingestion.domain.models import ParsedDocument
from app.ingestion.processing.profiles import default_profiles


def test_profile_falls_back_for_generic_text():
    result = default_profiles().classify(ParsedDocument("普通文本"))
    assert result.kind == "generic"
