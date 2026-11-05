from orch_ui.origin import check_request

P = 18080


def ok(method="GET", **h):
    return check_request(method, h, P) is None


def test_good_hosts():
    assert ok(Host=f"127.0.0.1:{P}")
    assert ok(Host=f"localhost:{P}")
    assert ok(host=f"localhost:{P}")  # header names are case-insensitive


def test_bad_hosts_rebinding():
    bad = [
        "evil.example", f"evil.example:{P}", "127.0.0.1", f"127.0.0.1:{P + 1}", f"localhost.:{P}",
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
