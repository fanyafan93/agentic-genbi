from app.agents.prompts import ANALYSIS_INSTRUCTIONS


def test_analysis_instructions_show_the_required_json_array_shapes() -> None:
    assert '"summary": ["one factual conclusion"]' in ANALYSIS_INSTRUCTIONS
    assert '"assumptions": []' in ANALYSIS_INSTRUCTIONS
    assert '"warnings": []' in ANALYSIS_INSTRUCTIONS
