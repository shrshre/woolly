"""Confirms the Ravelry client parses a search response correctly."""

from app.services.ravelry_client import RavelryClient

SAMPLE_SEARCH_RESPONSE = {
    "patterns": [
        {
            "id": 124700,
            "name": "Granny Square Cardigan",
            "permalink": "granny-square-cardigan",
            "free": True,
            "designer": {"id": 1, "name": "Jane Stitcher"},
            "first_photo": {
                "small_url": "https://images.example/small.jpg",
                "square_url": "https://images.example/square.jpg",
            },
        },
        {
            "id": 98765,
            "name": "Mystery Shawl",
            # No permalink, designer, or photo — fields the API may omit
        },
    ],
    "paginator": {"results": 2, "page": 1, "page_count": 1},
}


def test_parse_search_response():
    result = RavelryClient.parse_search_response("cardigan", SAMPLE_SEARCH_RESPONSE)

    assert result.query == "cardigan"
    assert result.total == 2
    assert len(result.patterns) == 2

    first = result.patterns[0]
    assert first.id == 124700
    assert first.name == "Granny Square Cardigan"
    assert first.designer == "Jane Stitcher"
    assert first.ravelry_url == "https://www.ravelry.com/patterns/library/granny-square-cardigan"
    assert first.photo_url == "https://images.example/small.jpg"
    assert first.free is True

    second = result.patterns[1]
    assert second.id == 98765
    assert second.designer is None
    assert second.ravelry_url is None
    assert second.photo_url is None


def test_parse_empty_response():
    result = RavelryClient.parse_search_response("zzzz", {"patterns": [], "paginator": {"results": 0}})

    assert result.patterns == []
    assert result.total == 0
