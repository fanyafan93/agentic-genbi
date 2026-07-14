from app.agents.prompts import ANALYSIS_INSTRUCTIONS


def test_analysis_instructions_show_the_required_json_array_shapes() -> None:
    assert '"summary": ["one factual conclusion"]' in ANALYSIS_INSTRUCTIONS
    assert '"assumptions": []' in ANALYSIS_INSTRUCTIONS
    assert '"warnings": []' in ANALYSIS_INSTRUCTIONS


def test_analysis_instructions_require_schema_qualified_names_for_cross_schema_queries() -> None:
    assert "schema-qualified table name" in ANALYSIS_INSTRUCTIONS
