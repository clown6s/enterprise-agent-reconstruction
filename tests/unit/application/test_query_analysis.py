from app.ingestion.application.query_analysis import analyze_query


def test_semantic_query_keeps_domain_term():
    result = analyze_query("Agent 如何工作的")
    assert result.kind == "semantic"
    assert result.exact_terms == ("Agent",)


def test_article_query_is_exact():
    result = analyze_query("第三十九条规定了什么")
    assert result.kind == "exact"
    assert "第三十九条" in result.exact_terms


def test_section_query_is_section():
    result = analyze_query("第十章讲了什么")
    assert result.kind == "section"
    assert result.section_terms == ("第十章",)
