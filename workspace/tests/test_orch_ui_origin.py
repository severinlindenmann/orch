from orch_ui.origin import check_request

P = 18080


def ok(method="GET", api=False, extra=(), **h):
    return check_request(method, h, P, api=api, extra_hosts=extra) is None


def test_good_hosts():
    assert ok(Host=f"127.0.0.1:{P}")
    assert ok(Host=f"localhost:{P}")
    assert ok(host=f"localhost:{P}")  # header names are case-insensitive


def test_bad_hosts_rebinding():
    bad = [
        "evil.example", f"evil.example:{P}", "127.0.0.1", f"localhost.:{P}",
        f"[::1]:{P}",
        f"127.0.0.1:{P}.evil.example", f"user@127.0.0.1:{P}", f"LOCALHOST:{P}", f" 127.0.0.1:{P}",
        f"127.0.0.1:{P}, evil.example", f"0.0.0.0:{P}", f"127.1:{P}", f"127.0.0.1:0{P}",
    ]  # fmt: skip
    for host in bad:
        assert not ok(Host=host), host
    assert not ok()  # no Host


def test_post_origin_must_match():
    host = f"127.0.0.1:{P}"
    assert ok("POST", Host=host, Origin=f"http://{host}")
    bad = [
        "null",
        "http://evil.example",
        f"http://localhost:{P}",
        f"https://{host}",
        f"http://{host}.evil.example",
        "",
    ]
    for origin in bad:
        assert not ok("POST", Host=host, Origin=origin), origin


def test_post_without_origin_for_curl_but_not_cross_site_browsers():
    host = f"127.0.0.1:{P}"
    assert ok("POST", Host=host)
    assert ok("POST", Host=host, **{"Sec-Fetch-Site": "same-origin"})
    assert not ok("POST", Host=host, **{"Sec-Fetch-Site": "cross-site"})
    assert not ok("POST", Host=host, **{"Sec-Fetch-Site": "same-site"})


def test_get_ignores_origin_but_not_host():
    host = f"127.0.0.1:{P}"
    assert ok("GET", Host=host, Origin="http://evil.example")
    assert not ok("GET", Host="evil.example")


def test_other_changing_methods_are_checked():
    host = f"localhost:{P}"
    for m in ("PUT", "PATCH", "DELETE", "post"):
        assert not ok(m, Host=host, Origin="http://evil.example")


def test_port_is_not_compared_only_digits_required():
    assert ok(Host=f"127.0.0.1:{P + 1}")
    assert ok(Host="localhost:3000")
    for host in ["127.0.0.1", "127.0.0.1:", f"127.0.0.1:0{P}", "127.0.0.1:80a", "127.0.0.1:-1", "127.0.0.1:0",
                 "127.0.0.1:65536", "127.0.0.1:1 2"]:  # fmt: skip
        assert not ok(Host=host), host
    assert not ok("POST", Host="127.0.0.1:9999", Origin=f"http://127.0.0.1:{P}")
    assert ok("POST", Host="127.0.0.1:9999", Origin="http://127.0.0.1:9999")


def test_api_get_refuses_cross_site():
    host = f"127.0.0.1:{P}"
    assert not ok("GET", api=True, Host=host, **{"Sec-Fetch-Site": "cross-site"})
    assert not ok("GET", api=True, Host=host, **{"Sec-Fetch-Site": "same-site"})
    assert ok("GET", api=True, Host=host, **{"Sec-Fetch-Site": "none"})
    assert ok("GET", api=True, Host=host, **{"Sec-Fetch-Site": "same-origin"})
    assert ok("GET", api=True, Host=host)  # curl, agents
    assert ok("GET", api=False, Host=host, **{"Sec-Fetch-Site": "cross-site"})  # pages open from links


def test_extra_hosts_only_when_configured():
    assert not ok(Host=f"landing.test:{P}")
    assert ok(extra=("landing.test",), Host=f"landing.test:{P}")
    assert not ok(extra=("landing.test",), Host=f"landing.test.evil.example:{P}")
    assert not ok(extra=("landing.test",), Host=f"evil.landing.test:{P}")
    assert not ok("POST", extra=("landing.test",), Host=f"landing.test:{P}", Origin=f"http://127.0.0.1:{P}")
    assert ok("POST", extra=("landing.test",), Host=f"landing.test:{P}", Origin=f"http://landing.test:{P}")


def test_duplicate_headers_refused():
    class Msg:  # like http.server's message: several values per name
        def __init__(self, d):
            self.d = d

        def items(self):
            return [(k, v[0]) for k, v in self.d.items()]

        def get_all(self, name, default=None):
            return self.d.get(name.lower(), default)

    host = f"127.0.0.1:{P}"
    one = Msg({"host": [host]})
    assert check_request("GET", one, P) is None
    assert check_request("GET", Msg({"host": [host, "evil.example"]}), P)
    assert check_request(
        "POST", Msg({"host": [host], "origin": [f"http://{host}", "http://evil.example"]}), P
    )
    assert check_request("GET", Msg({"host": [host], "sec-fetch-site": ["none", "cross-site"]}), P, api=True)
    assert check_request("GET", {"host": [host, host]}, P)  # plain mapping with a list
