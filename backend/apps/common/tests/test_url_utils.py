"""Unit tests for :mod:`apps.common.url_utils`."""

import pytest

from apps.common.url_utils import normalize_seed_url


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("bajajlifeinsurance.com", "https://bajajlifeinsurance.com/"),
        (
            "https://www.bajajlifeinsurance.com",
            "https://www.bajajlifeinsurance.com/",
        ),
        # The bug we are fixing: duplicated scheme.
        ("https://https://www.x.com", "https://www.x.com/"),
        ("https://https://https://x.com", "https://x.com/"),
        ("http://x.com:80/foo", "http://x.com/foo"),
        ("https://x.com:443", "https://x.com/"),
        ("//x.com/path", "https://x.com/path"),
        ("  https://x.com/  ", "https://x.com/"),
        ("HTTPS://X.COM", "https://x.com/"),
        ("https://x.com/a?b=1", "https://x.com/a?b=1"),
        ("https://пример.рф", "https://xn--e1afmkfd.xn--p1ai/"),
    ],
)
def test_normalize_seed_url_accepts(raw, expected):
    assert normalize_seed_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "not a url",
        "ftp://x.com",
        "https://",
        "",
    ],
)
def test_normalize_seed_url_rejects(raw):
    with pytest.raises(ValueError):
        normalize_seed_url(raw)
