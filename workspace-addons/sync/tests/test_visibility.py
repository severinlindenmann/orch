import urllib.error

import pytest

from orch_sync.visibility import remote_visibility


@pytest.mark.parametrize(
    "status, expected",
    [(200, "public"), (404, "unknown"), (403, "unknown"), (429, "unknown"), (None, "unknown")],
)
def test_visibility_stub(monkeypatch, status, expected):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def open_url(request, timeout):
        assert request.full_url == "https://api.github.com/repos/owner/repository"
        assert timeout <= 5
        if status is None:
            raise TimeoutError
        if status != 200:
            raise urllib.error.HTTPError(request.full_url, status, "", {}, None)
        response = Response()
        response.status = status
        return response

    monkeypatch.setattr("urllib.request.urlopen", open_url)
    assert remote_visibility("https://github.com/owner/repository.git") == expected
