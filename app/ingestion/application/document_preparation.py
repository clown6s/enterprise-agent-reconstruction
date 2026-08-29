"""文档解析、分类和可选的 OCR 预处理。"""
from dataclasses import replace

from ..domain.models import OcrStatus


class DocumentPreparation:
    def __init__(self, parser, classifier, ocr=None, structure_analyzer=None):
        self.parser = parser
        self.classifier = classifier
        self.ocr = ocr
        self.structure_analyzer = structure_analyzer

    def prepare(self, source):
        parsed = self.parser.parse(source)
        kind = self.classifier.classify(parsed, source)
        profile_parser = getattr(self.parser, "for_profile", lambda profile: self.parser)(kind)
        if profile_parser is not self.parser:
            parsed = profile_parser.parse(source)
            kind = self.classifier.classify(parsed, source)
        parsed = replace(parsed, profile=kind)
        if self.structure_analyzer and parsed.layout_blocks:
            parsed = replace(parsed, layout_blocks=self.structure_analyzer.analyze(parsed.layout_blocks))
        if self.ocr and kind == "technical_book":
            task = self.ocr.create_or_get(source)
            if task.status != OcrStatus.SUCCESS:
                return None, kind, task
            parsed = task.parsed or parsed
            kind = self.classifier.classify(parsed, source)
            parsed = replace(parsed, profile=kind)
        return parsed, kind, None
