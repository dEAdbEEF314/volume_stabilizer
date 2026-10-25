"""Tests for the To Do / Processed track list view (spec section 12)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from volume_stabilizer.api.app import app

STATIC_DIR = Path(__file__).parent.parent / "volume_stabilizer" / "static"
client = TestClient(app)


@pytest.fixture(scope="module")
def js():
    mini_racer = pytest.importorskip("py_mini_racer")
    ctx = mini_racer.MiniRacer()
    ctx.eval((STATIC_DIR / "js" / "track_view.js").read_text(encoding="utf-8"))

    def build_view(statuses, active_tab="todo", expanded=False):
        tracks = [{"id": str(i), "status": s} for i, s in enumerate(statuses)]
        payload = json.dumps([tracks, active_tab, expanded])
        raw = ctx.eval(
            f"JSON.stringify(TrackView.buildView(...{payload}))"
        )
        return json.loads(raw)

    return build_view


def ids(tracks):
    return [t["id"] for t in tracks]


MIXED = ["unprocessed", "converted", "error", "bypassed", "converted"]


def test_partition_classifies_error_as_todo(js):
    v = js(MIXED)
    assert v["todoCount"] == 2
    assert v["processedCount"] == 3
    assert v["stabilizedCount"] == 2
    assert v["bypassedCount"] == 1
    assert ids(v["main"]) == ["0", "2"]


def test_todo_tab_collapsed_by_default(js):
    v = js(MIXED)
    assert v["tab"] == "todo"
    assert v["showToggle"] is True
    assert v["expanded"] is False
    assert v["trailing"] == []


def test_todo_tab_expanded_shows_processed_trailing(js):
    v = js(MIXED, expanded=True)
    assert v["expanded"] is True
    assert ids(v["main"]) == ["0", "2"]
    assert ids(v["trailing"]) == ["1", "3", "4"]


def test_processed_tab_lists_only_processed_without_toggle(js):
    v = js(MIXED, active_tab="processed", expanded=True)
    assert v["tab"] == "processed"
    assert ids(v["main"]) == ["1", "3", "4"]
    assert v["showToggle"] is False
    assert v["trailing"] == []
    assert v["empty"] is None


def test_toggle_hidden_when_no_processed(js):
    v = js(["unprocessed", "error"], expanded=True)
    assert v["showToggle"] is False
    assert v["expanded"] is False
    assert v["trailing"] == []


def test_processed_tab_falls_back_to_todo_when_empty(js):
    v = js(["unprocessed"], active_tab="processed")
    assert v["tab"] == "todo"
    assert ids(v["main"]) == ["0"]


def test_all_processed_empty_state_on_todo_tab(js):
    v = js(["converted", "bypassed"])
    assert v["tab"] == "todo"
    assert v["empty"] == "all-processed"
    assert v["main"] == []
    assert v["showToggle"] is True


def test_no_tracks_empty_state(js):
    v = js([], active_tab="processed")
    assert v["tab"] == "todo"
    assert v["empty"] == "no-tracks"
    assert v["showToggle"] is False


@pytest.fixture(scope="module")
def tv():
    mini_racer = pytest.importorskip("py_mini_racer")
    ctx = mini_racer.MiniRacer()
    ctx.eval((STATIC_DIR / "js" / "track_view.js").read_text(encoding="utf-8"))

    def call(fn, *args):
        payload = json.dumps(list(args))
        return json.loads(ctx.eval(f"JSON.stringify(TrackView.{fn}(...{payload}))"))

    return call


def make_tracks(n, status="unprocessed", prefix="t"):
    return [{"id": f"{prefix}{i}", "status": status} for i in range(n)]


@pytest.mark.parametrize(
    "value, expected",
    [("10", 10), (20, 20), ("50", 50), ("100", 100), ("all", "all"),
     (None, 10), ("abc", 10), ("7", 10), (0, 10), ("", 10)],
)
def test_normalize_page_size(tv, value, expected):
    assert tv("normalizePageSize", value) == expected


@pytest.mark.parametrize(
    "current, total, expected",
    [
        (1, 1, [1]),
        (1, 3, [1, 2, 3]),
        (1, 10, [1, 2, 3, 4, 5]),
        (2, 10, [1, 2, 3, 4, 5]),
        (3, 10, [1, 2, 3, 4, 5]),
        (5, 10, [3, 4, 5, 6, 7]),
        (8, 10, [6, 7, 8, 9, 10]),
        (10, 10, [6, 7, 8, 9, 10]),
    ],
)
def test_page_links_window_of_five(tv, current, total, expected):
    assert tv("pageLinks", current, total) == expected


def test_paginate_slices_and_reports_range(tv):
    items = make_tracks(57)
    p = tv("paginate", items, 10, 2)
    assert [t["id"] for t in p["items"]] == [f"t{i}" for i in range(10, 20)]
    assert (p["page"], p["totalPages"], p["total"]) == (2, 6, 57)
    assert (p["start"], p["end"]) == (11, 20)
    assert p["hasPrev"] and p["hasNext"] and p["showPager"]


def test_paginate_last_page_is_partial(tv):
    p = tv("paginate", make_tracks(57), 10, 6)
    assert len(p["items"]) == 7
    assert (p["start"], p["end"]) == (51, 57)
    assert p["hasNext"] is False


def test_paginate_clamps_out_of_range_page(tv):
    items = make_tracks(25)
    assert tv("paginate", items, 10, 99)["page"] == 3
    assert tv("paginate", items, 10, 0)["page"] == 1
    assert tv("paginate", items, 10, "x")["page"] == 1


def test_paginate_all_and_single_page_hide_pager(tv):
    items = make_tracks(300)
    p = tv("paginate", items, "all", 1)
    assert len(p["items"]) == 300
    assert p["showPager"] is False
    assert tv("paginate", make_tracks(10), 10, 1)["showPager"] is False
    assert tv("paginate", [], 10, 1)["showPager"] is False


def test_build_view_pages_the_todo_list(js, tv):
    tracks = make_tracks(25)
    v = tv("buildView", tracks, "todo", False, 10, 3)
    assert v["paging"]["page"] == 3
    assert len(v["main"]) == 5
    assert v["todoCount"] == 25


def test_build_view_limits_expanded_section_and_reports_hidden(tv):
    tracks = make_tracks(3) + make_tracks(25, "converted", "p")
    v = tv("buildView", tracks, "todo", True, 10, 1)
    assert len(v["main"]) == 3
    assert [t["id"] for t in v["trailing"]] == [f"p{i}" for i in range(10)]
    assert v["trailingHidden"] == 15


def test_build_view_all_expands_everything(tv):
    tracks = make_tracks(3) + make_tracks(25, "converted", "p")
    v = tv("buildView", tracks, "todo", True, "all", 1)
    assert len(v["trailing"]) == 25
    assert v["trailingHidden"] == 0


def test_build_view_collapsed_has_no_hidden_count(tv):
    tracks = make_tracks(3) + make_tracks(25, "converted", "p")
    v = tv("buildView", tracks, "todo", False, 10, 1)
    assert v["trailing"] == []
    assert v["trailingHidden"] == 0


def test_build_view_processed_tab_is_paged(tv):
    tracks = make_tracks(3) + make_tracks(25, "converted", "p")
    v = tv("buildView", tracks, "processed", True, 20, 2)
    assert v["tab"] == "processed"
    assert len(v["main"]) == 5
    assert v["paging"]["totalPages"] == 2


def test_is_selected_defaults_and_overrides(tv):
    assert tv("isSelected", {"id": "a", "status": "unprocessed"}, {}) is True
    assert tv("isSelected", {"id": "a", "status": "error"}, {}) is True
    assert tv("isSelected", {"id": "a", "status": "converted"}, {}) is False
    assert tv("isSelected", {"id": "a", "status": "unprocessed"}, {"a": False}) is False
    assert tv("isSelected", {"id": "a", "status": "bypassed"}, {"a": True}) is True


def test_collect_selected_ids_spans_all_pages_on_todo_tab(tv):
    tracks = make_tracks(30) + make_tracks(5, "converted", "p")
    ids = tv("collectSelectedIds", tracks, "todo", {"t0": False, "p1": True})
    assert "t0" not in ids
    assert "t29" in ids
    assert "p1" in ids
    assert "p0" not in ids
    assert len(ids) == 29 + 1


def test_collect_selected_ids_processed_tab_only_explicit_processed(tv):
    tracks = make_tracks(5) + make_tracks(5, "converted", "p")
    assert tv("collectSelectedIds", tracks, "processed", {}) == []
    assert tv("collectSelectedIds", tracks, "processed", {"p2": True, "t1": True}) == ["p2"]


def test_index_html_has_tabs_and_loads_scripts_in_order():
    html = client.get("/").text
    for element_id in ("tab-todo", "tab-processed", "tab-todo-count", "tab-processed-count",
                       "page-size-select", "selected-count", "pager"):
        assert f'id="{element_id}"' in html
    assert html.index("/static/js/track_view.js") < html.index("/static/js/app.js")


@pytest.mark.parametrize("path", ["/static/js/track_view.js", "/static/js/app.js", "/static/css/app.css"])
def test_static_assets_served(path):
    assert client.get(path).status_code == 200


def test_app_js_wires_tab_logic():
    src = (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
    assert "TrackView.buildView" in src
    assert "vs.processedExpanded" in src
    assert 'data-section' in src or "dataset.section" in src
    assert "processed-toggle" in src
    assert "vs.pageSize" in src


def test_page_size_select_offers_five_steps():
    html = client.get("/").text
    block = html[html.index('id="page-size-select"'):]
    block = block[:block.index("</select>")]
    values = [v for v in ("10", "20", "50", "100", "all") if f'value="{v}"' in block]
    assert values == ["10", "20", "50", "100", "all"]
