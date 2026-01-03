import pytest

from tools.tv_tools import _normalize_url


@pytest.mark.parametrize(
    ("input_url", "expected"),
    [
        ("https://www.netflix.com/title/80057281", "http://www.netflix.com/watch/80057281"),
        (
            "https://www.hbomax.com/movies/broken-english/4cf01eb1-9257-4d25-8661-d0d9986ebdb0",
            "https://play.max.com/movie/4cf01eb1-9257-4d25-8661-d0d9986ebdb0",
        ),
        (
            "https://www.hbomax.com/series/urn:hbo:series:e6e7bad9-d48d-4434-b334-7c651ffc4bdf",
            "https://play.max.com/show/e6e7bad9-d48d-4434-b334-7c651ffc4bdf",
        ),
        (
            "https://tv.apple.com/us/show/the-morning-show/umc.cmc.1n9vozp2v4wqbmn1cx0x8k1xq",
            "https://tv.apple.com/show/umc.cmc.1n9vozp2v4wqbmn1cx0x8k1xq",
        ),
        (
            "https://tv.apple.com/show/umc.cmc.1n9vozp2v4wqbmn1cx0x8k1xq",
            "https://tv.apple.com/show/umc.cmc.1n9vozp2v4wqbmn1cx0x8k1xq",
        ),
        (
            "https://play.max.com/show/e6e7bad9-d48d-4434-b334-7c651ffc4bdf",
            "https://play.max.com/show/e6e7bad9-d48d-4434-b334-7c651ffc4bdf",
        ),
    ],
)
def test_normalize_url(input_url: str, expected: str):
    assert _normalize_url(input_url) == expected
