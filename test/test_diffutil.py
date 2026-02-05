from meld.matchers.diffutil import mark_conflict_markers_single
from meld.matchers.myers import DiffChunk


def test_mark_conflict_markers_both_sides():
    seq_a = [
        "not participating",
        "before start",
        "<<<<<<< START",
        "one line",
        "another line",
        "=======",
        "yet another",
        ">>>>>>> END",
    ]
    seq_b = [
        "not participating",
        "line0",
        "line1",
        "line2",
    ]
    chunk = DiffChunk("replace", 1, 8, 1, 4)
    expected_result = [
        DiffChunk("delete", 1, 2, 1, 1),
        DiffChunk("conflict", 2, 3, 1, 1),
        DiffChunk("replace", 3, 5, 1, 4),
        DiffChunk("conflict", 5, 6, 4, 4),
        DiffChunk("delete", 6, 7, 4, 4),
        DiffChunk("conflict", 7, 8, 4, 4),
    ]
    result = mark_conflict_markers_single(chunk, seq_a, seq_b)
    assert result == expected_result


def test_mark_conflict_markers_end():
    seq_a = [
        "not participating",
        "before end",
        ">>>>>>> END",
        "after end",
        "not participating",
    ]
    seq_b = [
        "not participating",
        "line0",
        "line1",
        "not participating",
    ]
    chunk = DiffChunk("replace", 1, 4, 1, 3)
    expected_result = [
        DiffChunk("replace", 1, 2, 1, 3),
        DiffChunk("conflict", 2, 3, 3, 3),
        DiffChunk("delete", 3, 4, 3, 3),
    ]
    result = mark_conflict_markers_single(chunk, seq_a, seq_b)
    assert result == expected_result


def test_mark_conflict_markers_empty_start():
    seq_a = [
        "before start",
        "<<<<<<< START",
        "=======",
        "something",
        ">>>>>>> END",
    ]
    seq_b = [
        "line0",
        "line1",
    ]
    chunk = DiffChunk("replace", 0, 5, 0, 2)
    expected_result = [
        DiffChunk("delete", 0, 1, 0, 0),
        DiffChunk("conflict", 1, 2, 0, 0),
        DiffChunk("conflict", 2, 3, 0, 0),
        DiffChunk("replace", 3, 4, 0, 2),
        DiffChunk("conflict", 4, 5, 2, 2),
    ]
    result = mark_conflict_markers_single(chunk, seq_a, seq_b)
    assert result == expected_result
