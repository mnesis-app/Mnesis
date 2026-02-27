from backend.memory import conversation_analysis_jobs


def test_analysis_stats_sample_errors_only_include_error_actions():
    result = {
        "write_stats": {"created": 0, "rejected": 2},
        "metrics": {"total_ms": 1200},
        "details": [
            {"action": "rejected_conflict", "message": "Potential duplicate memory."},
            {"action": "rejected_confidence", "message": "Below confidence threshold."},
            {"action": "error", "message": "Field 'decay_profile' not found in target schema"},
        ],
    }

    stats = conversation_analysis_jobs._analysis_stats_from_result(result)

    assert stats["rejected"] == 2
    assert stats["duration_ms"] == 1200
    assert stats["sample_errors"] == ["Field 'decay_profile' not found in target schema"]
