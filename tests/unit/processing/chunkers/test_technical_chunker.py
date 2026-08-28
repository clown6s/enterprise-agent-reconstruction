from app.ingestion.domain.models import LayoutBlock, ParsedDocument
from app.ingestion.processing.chunkers.technical import TechnicalChunker


def _document(blocks):
    return ParsedDocument("", profile="technical_book", layout_blocks=tuple(blocks))


def test_merges_consecutive_headings_with_following_body():
    document = _document([
        LayoutBlock("第 4 章 工具", "heading", 1),
        LayoutBlock("4.2 工具设计的通用原则", "heading", 1),
        LayoutBlock("4.2.1 能力表达形式的选择", "heading", 1),
        LayoutBlock("Agent 的能力有两种基本的表达形态。", "paragraph", 1),
    ])

    chunks = TechnicalChunker().chunk(document)

    assert len(chunks) == 1
    assert chunks[0].text.split("\n\n") == [
        "第 4 章 工具", "4.2 工具设计的通用原则",
        "4.2.1 能力表达形式的选择", "Agent 的能力有两种基本的表达形态。",
    ]
    assert chunks[0].section_path == (
        "第 4 章 工具", "4.2 工具设计的通用原则", "4.2.1 能力表达形式的选择",
    )


def test_does_not_treat_explanatory_number_as_heading():
    document = _document([
        LayoutBlock("第 7 章 模型后训练", "heading", 209),
        LayoutBlock("7.1 节已经讲透了 SFT 的本质。这一节用四个实验。", "paragraph", 209),
    ])

    chunks = TechnicalChunker().chunk(document)

    assert len(chunks) == 1
    assert chunks[0].section_path == ("第 7 章 模型后训练",)
    assert "7.1 节已经讲透了" in chunks[0].text


def test_starts_new_chunk_after_previous_heading_has_body():
    document = _document([
        LayoutBlock("第 1 章 基础", "heading", 1),
        LayoutBlock("第一节正文。", "paragraph", 1),
        LayoutBlock("1.1 细节", "heading", 2),
        LayoutBlock("细节正文。", "paragraph", 2),
    ])

    chunks = TechnicalChunker().chunk(document)

    assert len(chunks) == 2
    assert chunks[0].text == "第 1 章 基础\n\n第一节正文。"
    assert chunks[1].text == "1.1 细节\n\n细节正文。"
    assert chunks[1].page == 2


def test_experiment_labels_stay_in_the_section_chunk():
    document = _document([
        LayoutBlock("7.6 单轮强化学习：记忆与泛化的对照", "heading", 212),
        LayoutBlock("实验 7-10 ★★：AdaptThink——学会何时不思考", "paragraph", 212),
        LayoutBlock("实验 7-11 ★★：GeneralPoints——单轮 RL 的记忆与泛化对照", "paragraph", 212),
        LayoutBlock("实验正文。", "paragraph", 213),
        LayoutBlock("7.7 RLHF：从人类偏好到奖励模型", "heading", 214),
        LayoutBlock("新节正文。", "paragraph", 214),
    ])

    chunks = TechnicalChunker().chunk(document)

    assert len(chunks) == 2
    assert "实验 7-11" in chunks[0].text
    assert chunks[0].section_path == ("7.6 单轮强化学习：记忆与泛化的对照",)
