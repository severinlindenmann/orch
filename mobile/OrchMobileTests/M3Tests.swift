import XCTest
import Network
import WebKit
@testable import OrchMobile

private func json(_ name: String) throws -> [String: Any] {
    let url = Bundle(for: BundleToken.self).url(forResource: name, withExtension: "json")!
    return try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
}
private func hex(_ s: String) -> Data {
    var d = Data(), i = s.startIndex
    while i < s.endIndex { let j = s.index(i, offsetBy: 2); d.append(UInt8(s[i..<j], radix: 16)!); i = j }
    return d
}

// MARK: Published pages (contracts/crypto.md, vectors/publish-*.json)

final class PublishVectorTests: XCTestCase {
    func testGoodBlobDecrypts() throws {
        let v = try json("publish-blob-v1")
        for name in ["good", "good_with_note"] {
            let c = v[name] as! [String: Any]
            let key = Base64URL.decode(c["key_b64url"] as! String)!
            let f = try OPF1.open(hex(c["blob_hex"] as! String), key: key)
            XCTAssertEqual(String(data: f.bytes, encoding: .utf8), c["content_utf8"] as? String, name)
            let header = try JSONSerialization.jsonObject(with: Data((c["header_json"] as! String).utf8)) as! [String: Any]
            XCTAssertEqual(f.name, header["name"] as? String); XCTAssertEqual(f.type, header["type"] as? String)
            XCTAssertEqual(f.note, header["note"] as? String, name)
        }
    }
    func testBadBlobsAreRefused() throws {
        let v = try json("publish-blob-v1")
        for c in v["must_fail"] as! [[String: Any]] {
            let key = Base64URL.decode(c["key_b64url"] as! String)!
            XCTAssertThrowsError(try OPF1.open(hex(c["blob_hex"] as! String), key: key), c["name"] as! String)
        }
        let good = v["good"] as! [String: Any]
        var blob = hex(good["blob_hex"] as! String), key = Base64URL.decode(good["key_b64url"] as! String)!
        blob[blob.count - 20] ^= 1   // a flipped ciphertext bit: the tag check fails
        XCTAssertThrowsError(try OPF1.open(blob, key: key))
        XCTAssertThrowsError(try OPF1.open(Data("OPF1".utf8), key: key))
        key.removeLast()
        XCTAssertThrowsError(try OPF1.open(hex(good["blob_hex"] as! String), key: key))
    }
    func testGoodBundlesUnpack() throws {
        let v = try json("publish-bundle-v1")
        for name in ["good", "good_no_index"] {
            let c = v[name] as! [String: Any]
            let b = try PublishBundle.parse(hex(c["bundle_hex"] as! String))
            XCTAssertEqual(b.entry, c["entry"] as? String, name)
            let files = c["files"] as! [[String: Any]]
            XCTAssertEqual(b.files.count, files.count, name)
            for f in files {
                let got = b.file(at: f["path"] as! String)
                XCTAssertEqual(got.flatMap { String(data: $0.data, encoding: .utf8) }, f["content_utf8"] as? String, name)
                XCTAssertEqual(got?.type, f["type"] as? String)
            }
        }
    }
    func testBadBundlesAreRefused() throws {
        for c in try json("publish-bundle-v1")["must_fail"] as! [[String: Any]] {
            XCTAssertThrowsError(try PublishBundle.parse(hex(c["bundle_hex"] as! String)), c["name"] as! String)
        }
    }
    func testBundleSizesCannotOverflow() throws {
        // Two files whose sizes add up past Int.max must be refused, not trap.
        let idx = #"{"v":1,"entry":"a.html","files":[{"path":"a.html","type":"text/html","size":9223372036854775807},{"path":"b.html","type":"text/html","size":9223372036854775807}]}"#
        var d = Data([0, 0, 0, UInt8(idx.utf8.count)]); d.append(Data(idx.utf8)); d.append(Data(repeating: 0, count: 8))
        XCTAssertThrowsError(try PublishBundle.parse(d))
    }
    func testPublishLinkNeedsAFileIdAndAKey() {
        let key = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
        let l = PublishLink(URL(string: "https://publish.example.org/f/abc123#k=\(key)")!)
        XCTAssertEqual(l?.blobURL.absoluteString, "https://publish.example.org/f/abc123/blob")
        XCTAssertEqual(l?.key.count, 32)
        XCTAssertNil(PublishLink(URL(string: "https://publish.example.org/f/abc123")!), "no key")
        XCTAssertNil(PublishLink(URL(string: "https://publish.example.org/f/abc123#k=short")!), "short key")
        XCTAssertNil(PublishLink(URL(string: "https://publish.example.org/a/shop/?token=x")!), "an app is not a file")
        XCTAssertNil(PublishLink(URL(string: "ftp://publish.example.org/f/abc#k=\(key)")!))
    }
    func testFetcherMapsStatusAndDecrypts() async throws {
        let c = try json("publish-blob-v1")["good"] as! [String: Any]
        let blob = hex(c["blob_hex"] as! String)
        let link = PublishLink(URL(string: "https://p.example.org/f/x1\(c["url_fragment"] as! String)")!)!
        StubURLProtocol.respond = { _ in (200, blob) }
        let cfg = URLSessionConfiguration.ephemeral; cfg.protocolClasses = [StubURLProtocol.self]
        let f = PublishFetcher(session: URLSession(configuration: cfg))
        let content = try await f.load(link)
        guard case .file(let file) = content else { return XCTFail("text/plain is a plain file") }
        XCTAssertEqual(file.name, "hello.txt")
        StubURLProtocol.respond = { _ in (410, Data()) }
        do { _ = try await f.load(link); XCTFail() } catch { XCTAssertEqual(error as? PublishError, .expired) }
        StubURLProtocol.respond = { _ in (200, Data(repeating: 1, count: 64)) }
        do { _ = try await f.load(link); XCTFail() } catch { XCTAssertEqual(error as? PublishError, .broken) }
    }
    @MainActor func testNetworkBlockRulesCompile() async throws {
        let list = try await WKContentRuleListStore.default().compileContentRuleList(forIdentifier: "m3-test", encodedContentRuleList: NetworkBlock.rules)
        XCTAssertNotNil(list)
        try await WKContentRuleListStore.default().removeContentRuleList(forIdentifier: "m3-test")
    }
}

final class StubURLProtocol: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var respond: (URLRequest) -> (Int, Data) = { _ in (200, Data()) }
    /// A request that never answers; `stopped` counts requests that were cancelled.
    nonisolated(unsafe) static var hang = false
    nonisolated(unsafe) static var stopped = 0
    nonisolated(unsafe) static var started = 0
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        if Self.hang { Self.started += 1; return }
        let (code, data) = Self.respond(request)
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { if Self.hang { Self.stopped += 1 } }
}

// MARK: Comment pins and anchors

@MainActor
final class PinTests: XCTestCase {
    private let item = ArtifactItem(id: "a_1", title: "Landing", kind: .html, artifactId: "a_0123456789ab", rev: "rev1234567890",
                                    conversation: .topic(workspace: "ws_1", ticket: "t_1"))

    func testPinsAreNumberedAndRenumberedAfterDelete() {
        let s = PinStore()
        for i in 0..<3 {
            s.beginPin(anchor: AnchorMaker.image(x: 0.1 * Double(i), y: 0.5), place: .init(x: 0.1, y: 0.5))
            s.editing?.text = "c\(i)"; XCTAssertTrue(s.saveEdit())
        }
        XCTAssertEqual(s.pins.map(\.n), [1, 2, 3])
        s.remove(2)
        XCTAssertEqual(s.pins.map(\.n), [1, 2]); XCTAssertEqual(s.pins.map(\.text), ["c0", "c2"])
    }
    func testEmptyPinIsNotSaved() {
        let s = PinStore()
        s.beginPin(anchor: AnchorMaker.image(x: 0.5, y: 0.5), place: .init(x: 0.5, y: 0.5))
        XCTAssertFalse(s.saveEdit()); XCTAssertEqual(s.count, 0)
        s.editing?.voiceFile = URL(fileURLWithPath: "/tmp/v.m4a")
        XCTAssertTrue(s.saveEdit(), "a voice comment alone is a comment")
    }
    func testChangesDraftCarriesIdRevisionAndPins() throws {
        let s = PinStore()
        XCTAssertNil(s.changesDraft(for: item), "changes need at least one pin")
        s.beginPin(anchor: AnchorMaker.html(selector: "#hero > h1", quote: "Good things", offset: 120, viewportW: 390)!, place: .init(x: 0.4, y: 0.1))
        s.editing?.text = "Shorter"; s.saveEdit()
        let d = try XCTUnwrap(s.changesDraft(for: item))
        XCTAssertEqual(d.artifactId, "a_0123456789ab"); XCTAssertEqual(d.artifactRev, "rev1234567890"); XCTAssertEqual(d.verdict, .changes)
        XCTAssertEqual(d.pins.first?.anchor.selector, "#hero > h1"); XCTAssertEqual(d.pins.first?.anchor.viewportW, 390)
        // and it is a valid message for the relay
        let draft = MessageDraft(feedback: d)
        XCTAssertNotNil(draft.feedback)
        let approve = try XCTUnwrap(PinStore.approveDraft(for: item))
        XCTAssertEqual(approve.verdict, .approve); XCTAssertTrue(approve.pins.isEmpty)
    }
    func testFeedbackNeedsATopicAndRevision() {
        var i = item; i.conversation = .general(workspace: "ws_1"); XCTAssertFalse(i.canGiveFeedback)
        i = item; i.rev = nil; XCTAssertFalse(i.canGiveFeedback); XCTAssertNil(PinStore.approveDraft(for: i))
        XCTAssertTrue(item.canGiveFeedback)
    }
    func testAnchorShapes() {
        let p = AnchorMaker.pdf(page: 2, x: 1.4, y: -0.2)
        XCTAssertEqual(p.type, .pdf); XCTAssertEqual(p.page, 2); XCTAssertEqual(p.x, 1); XCTAssertEqual(p.y, 0)
        let im = AnchorMaker.image(x: 0.25, y: 0.75); XCTAssertEqual(im.type, .image); XCTAssertEqual(im.x, 0.25)
        XCTAssertNil(AnchorMaker.html(selector: "", quote: "  ", offset: 0, viewportW: 390), "needs a selector or a quote")
        XCTAssertEqual(AnchorMaker.html(selector: nil, quote: String(repeating: "x", count: 400), offset: -5, viewportW: 390)?.quote?.count, 160)
    }
    func testScriptMessageBecomesAnAnchor() throws {
        let body: [String: Any] = ["kind": "place", "selector": "p:nth-of-type(2)", "quote": "Hello there", "offset": 340, "viewportW": 390, "fx": 0.3, "fy": 0.55]
        let r = try XCTUnwrap(AnchorMaker.html(fromScript: body))
        XCTAssertEqual(r.anchor.type, .html); XCTAssertEqual(r.anchor.offset, 340); XCTAssertEqual(r.place.y, 0.55)
        XCTAssertNil(AnchorMaker.html(fromScript: ["kind": "edit", "n": 1]))
        XCTAssertNil(AnchorMaker.html(fromScript: "nope"))
    }
    func testAnchorsEncodeLikeTheContract() throws {
        let a = AnchorMaker.html(selector: "h1", quote: nil, offset: 10, viewportW: 390)!
        let data = try JSONCoding.encoder.encode(Pin(n: 1, anchor: a, text: "x"))
        let o = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        let anchor = o["anchor"] as! [String: Any]
        XCTAssertEqual(anchor["type"] as? String, "html"); XCTAssertEqual(anchor["viewport_w"] as? Int, 390); XCTAssertEqual(anchor["offset"] as? Int, 10)
    }
    func testArtifactItemKinds() {
        XCTAssertEqual(ArtifactItem(TicketSnapshot.Attachment(kind: "html", title: "Page", url: "https://x.example/f/a#k=b", artifactId: "a_1", rev: "r")).kind, .html)
        XCTAssertEqual(ArtifactItem(TicketSnapshot.Attachment(kind: "file", blobId: "b", name: "Report.PDF")).kind, .pdf)
        XCTAssertEqual(ArtifactItem(TicketSnapshot.Attachment(kind: "pr", title: "PR", url: "https://github.com/x")).kind, .link)
        XCTAssertEqual(ArtifactItem(MessageAttachment(blobId: "b", kind: .image, name: "p.jpg", size: 1, mime: "image/jpeg")).kind, .image)
        XCTAssertEqual(ArtifactItem(MessageAttachment(blobId: "b", kind: .file, name: "a.bin", size: 1, mime: "application/pdf")).kind, .pdf)
    }
}

// MARK: The page sandbox (WKWebView, no network)

@MainActor
final class PublishWebViewTests: XCTestCase {
    final class Handler: NSObject, WKScriptMessageHandler {
        var bodies: [Any] = []
        func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) { bodies.append(m.body) }
    }
    final class Nav: NSObject, WKNavigationDelegate {
        var done: CheckedContinuation<Void, Never>?
        func webView(_ w: WKWebView, didFinish n: WKNavigation!) { done?.resume(); done = nil }
    }

    private func open(_ html: String, handler: Handler? = nil) async throws -> (WKWebView, Nav, PageSchemeHandler) {
        let pages = PageSchemeHandler(bundle: PublishBundle(entry: "index.html", files: [.init(path: "index.html", type: "text/html", data: Data(html.utf8))]))
        let web = PublishWebView.make(handler: pages, pins: handler)
        web.frame = CGRect(x: 0, y: 0, width: 390, height: 600)
        let nav = Nav(); web.navigationDelegate = nav
        let ok = await PublishWebView.block(web); XCTAssertTrue(ok)
        await withCheckedContinuation { c in nav.done = c; web.load(URLRequest(url: PageSchemeHandler.base.appendingPathComponent("index.html"))) }
        return (web, nav, pages)
    }

    private var retained: [AnyObject] = []
    /// The page opened exactly as the viewer does: the production coordinator (scheme handler, navigation delegate, scripts, rule list).
    private func openProduction(_ html: String) async throws -> WKWebView {
        let surface = HTMLSurface(content: .publish(.page(html: html, name: "index.html")), commentMode: false, store: PinStore())
        let c = HTMLSurface.Coordinator(surface)
        let web = PublishWebView.make(handler: c.pages, pins: c)
        web.frame = CGRect(x: 0, y: 0, width: 390, height: 600)
        web.navigationDelegate = c
        retained += [c, web]
        c.load(web)
        for _ in 0..<100 {
            // Read from the page itself: web.url changes while the first (blank) document is still the one on screen.
            let state = try await web.evaluateJavaScript("location.protocol + document.readyState + (document.body ? 'B' : '')") as? String
            if state == "orch-page:completeB" { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertEqual(web.url?.scheme, "orch-page", "the page loaded")
        return web
    }

    /// Link activation connects to the link's host before the navigation policy can cancel it: the guards must stop every way of activating one.
    func testLinkActivationNeverConnects() async throws {
        let host = try await LoopbackHost.start()
        defer { host.stop() }
        _ = try? await URLSession.shared.data(from: URL(string: "http://127.0.0.1:\(host.port)/sanity")!)
        XCTAssertGreaterThan(host.connections, 0, "the host is reachable, so the test can fail")
        let before = host.connections
        let base = "http://127.0.0.1:\(host.port)"
        let html = """
        <body><a id=att href="\(base)/att">x</a><a id=frag href="#end">f</a><div style="height:3000px"></div><p id=end>end</p>
        <script>
        document.getElementById('att').click();
        var d = document.createElement('a'); d.href = '\(base)/detached'; d.click();
        var t = document.createElement('a'); t.href = '\(base)/blank'; t.target = '_blank'; document.body.appendChild(t); t.click();
        var dl = document.createElement('a'); dl.href = '\(base)/dl'; dl.download = 'x'; dl.click();
        var h = document.createElement('div'); var s = h.attachShadow({mode: 'closed'}); var sa = document.createElement('a'); sa.href = '\(base)/shadow'; s.appendChild(sa); sa.click();
        document.getElementById('att').dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
        var la = document.createElement('a'); la.href = '\(base)/span'; var sp = document.createElement('span'); la.appendChild(sp); sp.click();
        var tn = document.createElement('a'); tn.href = '\(base)/text'; tn.textContent = 'x'; tn.firstChild.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        document.getElementById('att').firstChild.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        var da = document.createElement('a'); da.href = '\(base)/dshadow'; var dh = document.createElement('div'); da.appendChild(dh);
        var dr = dh.attachShadow({mode: 'open'}); var ds = document.createElement('span'); dr.appendChild(ds); ds.click();
        var sh = document.createElement('div'); var sr = sh.attachShadow({mode: 'open'}); sr.innerHTML = '<a href="\(base)/slot"><slot></slot></a>';
        var ss = document.createElement('span'); sh.appendChild(ss); ss.click();
        document.getElementById('frag').click();
        </script></body>
        """
        let web = try await openProduction(html)
        try await Task.sleep(for: .milliseconds(1000))
        XCTAssertEqual(host.connections, before, "no link activation reached the host")
        let hash = try await web.evaluateJavaScript("location.hash") as? String
        XCTAssertEqual(hash, "#end", "a #fragment link still works")
    }

    /// The page shadows the properties a naive guard would read, then activates a link; and a closed shadow root cannot hide a link from the tap listener.
    func testLinkGuardSurvivesTamperingAndClosedShadowRoots() async throws {
        let host = try await LoopbackHost.start()
        defer { host.stop() }
        _ = try? await URLSession.shared.data(from: URL(string: "http://127.0.0.1:\(host.port)/sanity")!)
        XCTAssertGreaterThan(host.connections, 0, "the host is reachable, so the test can fail")
        let before = host.connections
        let base = "http://127.0.0.1:\(host.port)"
        let html = """
        <body><a id=att href="\(base)/att">x</a><div id=h></div>
        <script>
        Object.defineProperty(Node.prototype, 'nodeType', { get: function () { return 3; }, configurable: true });
        Object.defineProperty(Event.prototype, 'type', { get: function () { return 'nothing'; }, configurable: true });
        Object.defineProperty(Element.prototype, 'closest', { value: function () { return null; }, configurable: true });
        Object.defineProperty(HTMLAnchorElement.prototype, 'href', { get: function () { return 'orch-page://page/x'; }, configurable: true });
        var a = document.getElementById('att');
        a.click();
        a.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        var d = document.createElement('a'); d.href = '\(base)/detached'; d.click();
        var s = document.getElementById('h').attachShadow({ mode: 'closed' });
        var sa = document.createElement('a'); sa.id = 'sa'; sa.href = '\(base)/shadow'; sa.textContent = 'in shadow'; s.appendChild(sa);
        </script></body>
        """
        let web = try await openProduction(html)
        // The page cannot reach its closed root any more (it was made open); a native click from the isolated world is what a tap does.
        let open = try await web.evaluateJavaScript("document.getElementById('h').shadowRoot !== null", in: nil, contentWorld: NetworkBlock.hintWorld) as? Bool
        XCTAssertEqual(open, true, "attachShadow was forced to open")
        _ = try await web.evaluateJavaScript("document.getElementById('h').shadowRoot.getElementById('sa').click()", in: nil, contentWorld: NetworkBlock.hintWorld)
        try await Task.sleep(for: .milliseconds(1000))
        XCTAssertEqual(host.connections, before, "no connection reached the host")
    }

    /// Three more ways round the guard: a replaced URL, declarative shadow roots (from the server markup and from setHTMLUnsafe), a bare <a> inside a link.
    func testLinkGuardSurvivesUrlTamperDeclarativeShadowAndNestedAnchors() async throws {
        let host = try await LoopbackHost.start()
        defer { host.stop() }
        _ = try? await URLSession.shared.data(from: URL(string: "http://127.0.0.1:\(host.port)/sanity")!)
        let before = host.connections
        let base = "http://127.0.0.1:\(host.port)"
        let html = """
        <body><a id=att href="\(base)/att">x</a>
        <div id=decl><template shadowrootmode="closed"><a id=sa href="\(base)/decl">decl</a></template></div>
        <div id=unsafe></div>
        <script>
        Object.defineProperty(URL.prototype, 'protocol', { get: function () { return 'orch-page:'; }, configurable: true });
        window.URL = function () { this.protocol = 'orch-page:'; };
        document.getElementById('att').click();
        var u = document.getElementById('unsafe');
        if (u.setHTMLUnsafe) u.setHTMLUnsafe('<template shadowrootmode=closed><a id=sb href="\(base)/unsafe">unsafe</a></template>');
        var outer = document.createElement('a'); outer.href = '\(base)/nested'; var inner = document.createElement('a');
        var span = document.createElement('span'); inner.appendChild(span); outer.appendChild(inner); document.body.appendChild(outer);
        span.click();
        </script></body>
        """
        let web = try await openProduction(html)
        let js = "(function(){ var r=[]; ['decl','unsafe'].forEach(function(id){ var root=document.getElementById(id).shadowRoot; r.push(root ? 'open' : 'none'); if(root){ var a=root.querySelector('a'); if(a) a.click(); } }); return r.join(','); })()"
        let state = try await web.evaluateJavaScript(js, in: nil, contentWorld: NetworkBlock.hintWorld) as? String
        XCTAssertTrue(state?.hasPrefix("open") == true, "the declarative root was made open: \(state ?? "nil")")
        try await Task.sleep(for: .milliseconds(1000))
        XCTAssertEqual(host.connections, before, "no connection reached the host")
    }

    /// A link buried deeper than the guard's step cap is blocked, not allowed.
    func testLinkNestedBeyondTheStepCapIsBlocked() async throws {
        let host = try await LoopbackHost.start()
        defer { host.stop() }
        _ = try? await URLSession.shared.data(from: URL(string: "http://127.0.0.1:\(host.port)/sanity")!)
        let before = host.connections
        let html = """
        <body><script>
        var a = document.createElement('a'); a.href = 'http://127.0.0.1:\(host.port)/deep';
        var n = a; for (var i = 0; i < 10001; i++) { var d = document.createElement('div'); n.appendChild(d); n = d; }
        n.click();
        </script></body>
        """
        _ = try await openProduction(html)
        try await Task.sleep(for: .milliseconds(1000))
        XCTAssertEqual(host.connections, before, "no connection reached the host")
    }

    func testFreshAboutBlankFrameStillHasTheWebRTCStub() async throws {
        let web = try await openProduction("<body><script>try { var f = document.body.appendChild(document.createElement('iframe')); try { new f.contentWindow.RTCPeerConnection(); window.__r = 'works'; } catch (e) { window.__r = 'throws'; } } catch (e) { window.__r = 'error ' + e; }</script></body>")
        let r = try await web.evaluateJavaScript("window.__r") as? String
        XCTAssertEqual(r, "throws")
    }

    func testResponseHeadersAndCSPCloseFormsAndBase() {
        XCTAssertTrue(NetworkBlock.csp.contains("form-action 'none'") && NetworkBlock.csp.contains("base-uri 'none'"))
    }

    func testPageCannotReachTheNetworkOrUseWebRTC() async throws {
        // A real host that answers every request and counts the connections: the page must never reach it.
        let host = try await LoopbackHost.start()
        defer { host.stop() }
        _ = try? await URLSession.shared.data(from: URL(string: "http://127.0.0.1:\(host.port)/sanity")!)
        XCTAssertGreaterThan(host.connections, 0, "the host is reachable, so the test can fail")
        let before = host.connections
        let html = """
        <head><link rel="preconnect" href="http://127.0.0.1:\(host.port)"><link rel='dns-prefetch' href='http://127.0.0.1:\(host.port)'>
        <link rel="&#112;reconnect" href="http://127.0.0.1:\(host.port)/entity"></head>
        <body><script>
        var r = {}; window.__r = r;
        fetch('http://127.0.0.1:\(host.port)/x').then(function(){ r.fetch = 'ok'; }, function(){ r.fetch = 'blocked'; });
        var x = new XMLHttpRequest(); x.open('GET', 'http://127.0.0.1:\(host.port)/x'); x.onload = function(){ r.xhr = 'ok'; }; x.onerror = function(){ r.xhr = 'blocked'; }; x.send();
        try { var w = new WebSocket('ws://127.0.0.1:\(host.port)/x'); w.onopen = function(){ r.ws = 'ok'; }; w.onerror = function(){ r.ws = 'blocked'; }; } catch (e) { r.ws = 'blocked'; }
        var i = new Image(); i.onload = function(){ r.img = 'ok'; }; i.onerror = function(){ r.img = 'blocked'; }; i.src = 'http://127.0.0.1:\(host.port)/p.png';
        try { new RTCPeerConnection(); r.rtc = 'present'; } catch (e) { r.rtc = 'gone'; }
        </script></body>
        """
        let web = try await openProduction(html)
        var result: [String: String] = [:]
        for _ in 0..<50 {
            let json = try await web.evaluateJavaScript("JSON.stringify(window.__r || {})") as? String ?? "{}"
            result = (try? JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: String]) ?? [:]
            if result.count == 5 { break }
            try await Task.sleep(for: .milliseconds(200))
        }
        XCTAssertEqual(result, ["fetch": "blocked", "xhr": "blocked", "ws": "blocked", "img": "blocked", "rtc": "gone"])
        try await Task.sleep(for: .milliseconds(500))
        XCTAssertEqual(host.connections, before, "no connection reached the host: not by script, not by a preconnect hint (also the entity-encoded one the strip cannot see)")
    }

    func testPreconnectAndPrefetchHintsAreStripped() {
        let html = #"<head><link rel="stylesheet" href="a.css"><link rel="preconnect" href="https://x.example"><link href="https://y.example" REL='dns-prefetch'><link rel="icon preload prefetch" href="z"><link rel=prerender href=q></head><p>kept</p>"#
        let out = String(decoding: NetworkBlock.stripHints(from: Data(html.utf8))!, as: UTF8.self)
        XCTAssertFalse(out.contains("preconnect") || out.contains("prefetch") || out.contains("prerender"))
        XCTAssertTrue(out.contains(#"<link rel="stylesheet" href="a.css">"#) && out.contains("<p>kept</p>"))
    }

    func testXHTMLAndSVGPagesAreStrippedToo() {
        let hint = #"<link rel="preconnect" href="https://x.example"/>"#
        for type in ["application/xhtml+xml", "image/svg+xml", "text/xml", "application/xml", "text/html; charset=utf-8"] {
            let out = NetworkBlock.serve(type: type, data: Data("<root>\(hint)<p>kept</p></root>".utf8))
            XCTAssertEqual(String(decoding: out.data, as: UTF8.self), "<root> <p>kept</p></root>", type)
            XCTAssertEqual(out.type, String(type.split(separator: ";")[0]) + "; charset=utf-8", type)
        }
    }
    func testNonUTF8MarkupAndUnknownTypesAreServedAsOctetStream() {
        let bad = NetworkBlock.serve(type: "text/html", data: Data([0x3c, 0x70, 0x3e, 0xff, 0xfe, 0x3c, 0x2f, 0x70, 0x3e]))
        XCTAssertEqual(bad.type, "application/octet-stream")
        for type in ["application/x-shockwave-flash", "text/plain", "application/octet-stream", "multipart/related", "", "text/html-sandboxed"] {
            XCTAssertEqual(NetworkBlock.serve(type: type, data: Data("<p>x</p>".utf8)).type, "application/octet-stream", type)
        }
        for ok in ["text/css", "image/png", "font/woff2", "application/json", "application/pdf", "text/javascript"] {
            let isText = ["text/css", "application/json", "text/javascript"].contains(ok)
            XCTAssertEqual(NetworkBlock.serve(type: ok, data: Data("x".utf8)).type, isText ? ok + "; charset=utf-8" : ok)
        }
    }
    /// Removing one tag must never glue its neighbours into a new one.
    func testRemovingATagCannotSpliceANewOne() {
        let cases = [
            "<li<meta http-equiv=x-dns-prefetch-control content=on>nk rel=preconnect href=//x>",     // meta inside a link
            "<me<link rel=preconnect href=//x>ta http-equiv=x-dns-prefetch-control content=on>",     // link inside a meta
            "<li<link rel=preconnect>nk rel=preconnect href=//x>",                                  // doubled
            "<lin<li<link rel=preconnect>nk rel=preconnect>k rel=preconnect href=//x>"]              // nested twice
        for html in cases {
            let out = NetworkBlock.stripHints(from: Data(html.utf8)).map { String(decoding: $0, as: UTF8.self) } ?? "<unstable>"
            XCTAssertFalse(out.lowercased().contains("<link"), "\(html) -> \(out)")
            XCTAssertFalse(out.lowercased().contains("<meta"), "\(html) -> \(out)")
            XCTAssertEqual(NetworkBlock.stripHints(from: Data(out.utf8)).map { String(decoding: $0, as: UTF8.self) }, out, "stable: a second run changes nothing")
        }
    }
    func testPagesThatDoNotSettleAreServedAsPlainText() {
        let html = Data("<link rel=preconnect href=//x>".utf8)
        XCTAssertNil(NetworkBlock.stripHints(from: html, passes: 0), "no pass left to prove it stable")
        XCTAssertNotNil(NetworkBlock.stripHints(from: html))
    }
    func testDeclarativeShadowRootsAreServedOpen() {
        let html = #"<template shadowrootmode=closed><a href=x></a></template><template ShadowRoot='closed'></template><template shadowrootmode = "closed"></template>"#
        let out = String(decoding: NetworkBlock.stripHints(from: Data(html.utf8))!, as: UTF8.self).lowercased()
        XCTAssertFalse(out.contains("closed"), out)
        XCTAssertEqual(out.components(separatedBy: "=\"open\"").count - 1, 3)
    }
    func testPublishersCharsetIsNeverPassedOn() {
        let out = NetworkBlock.serve(type: "text/html; charset=iso-8859-1", data: Data("<p>caf\u{e9}</p>".utf8))
        XCTAssertEqual(out.type, "text/html; charset=utf-8", "WebKit decodes the bytes that were checked")
        XCTAssertEqual(NetworkBlock.serve(type: "IMAGE/PNG; foo=bar", data: Data([1])).type, "image/png")
    }
    func testDNSPrefetchMetaIsStrippedAndForcedOff() async throws {
        let on = #"<head><META content="on" http-equiv="X-DNS-Prefetch-Control"><meta http-equiv='x-dns-prefetch-control' content='on'></head><p>kept</p>"#
        XCTAssertEqual(String(decoding: NetworkBlock.stripHints(from: Data(on.utf8))!, as: UTF8.self).replacingOccurrences(of: "  ", with: " "), "<head> </head><p>kept</p>")
        // A page that adds or flips such a meta itself: the isolated script turns every one of them off again.
        let (web, _, _) = try await open("<head></head><body><script>var m=document.createElement('meta'); m.httpEquiv='x-dns-prefetch-control'; m.content='on'; document.head.appendChild(m); setTimeout(function(){ m.content='on'; }, 100);</script></body>")
        try await Task.sleep(for: .milliseconds(500))
        let values = try await web.evaluateJavaScript("Array.from(document.querySelectorAll('meta[http-equiv]')).map(function(m){return m.content;}).join(',')") as? String
        let all = (values ?? "").split(separator: ",")
        XCTAssertFalse(all.isEmpty); XCTAssertTrue(all.allSatisfy { $0 == "off" }, "every meta says off: \(values ?? "-")")
    }
    func testHintScriptRemovesAddedHintsAndTurnsPrefetchOff() async throws {
        let (web, _, _) = try await open("<head></head><body><script>var l=document.createElement('link'); l.rel='preconnect'; l.href='http://127.0.0.1:9'; document.head.appendChild(l);</script></body>")
        try await Task.sleep(for: .milliseconds(300))
        let n = try await web.evaluateJavaScript("document.querySelectorAll('link[rel~=preconnect]').length") as? Int
        XCTAssertEqual(n, 0, "a hint the page adds itself is removed again")
        let meta = try await web.evaluateJavaScript("document.querySelector('meta[http-equiv=\"x-dns-prefetch-control\"]').content") as? String
        XCTAssertEqual(meta, "off")
    }
    func testAboutBlankIsNotALocalPage() {
        XCTAssertTrue(PublishWebView.isLocal(URL(string: "orch-page://page/index.html")))
        XCTAssertFalse(PublishWebView.isLocal(URL(string: "about:blank")))
        XCTAssertFalse(PublishWebView.isLocal(URL(string: "https://example.org")))
    }

    func testWebRTCStaysGoneEvenIfThePageTriesToRestoreIt() async throws {
        let html = """
        <body><script>
        var r = {}; window.__r = r;
        try { delete window.RTCPeerConnection; } catch (e) {}
        try { Object.defineProperty(window, 'RTCPeerConnection', { value: 1 }); } catch (e) {}
        try { new RTCPeerConnection(); r.ctor = 'works'; } catch (e) { r.ctor = 'throws'; }
        try { var f = document.createElement('iframe'); f.src = 'about:blank'; document.body.appendChild(f); try { new f.contentWindow.RTCPeerConnection(); r.frame = 'fresh'; } catch (e) { r.frame = 'none'; } } catch (e) { r.frame = 'none'; }
        </script></body>
        """
        let (web, _, _) = try await open(html)
        let json = try await web.evaluateJavaScript("JSON.stringify(window.__r || {})") as? String ?? "{}"
        let r = (try? JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: String]) ?? [:]
        XCTAssertEqual(r["ctor"], "throws")
        XCTAssertNotEqual(r["frame"], "fresh", "a child frame must not give a fresh WebRTC")
        XCTAssertTrue(NetworkBlock.csp.contains("frame-src 'none'") && NetworkBlock.csp.contains("worker-src 'none'") && NetworkBlock.csp.contains("connect-src 'none'"))
    }

    func testTapInCommentModePostsSelectorQuoteOffset() async throws {
        let h = Handler()
        let (web, _, _) = try await open("<meta name=viewport content='width=device-width'><body style='margin:0'><section id=hero><h1 style='margin:0;height:200px'>Good things</h1></section><p>Second paragraph</p></body>", handler: h)
        let w = AnchorScript.world
        _ = try await web.evaluateJavaScript(AnchorScript.setMode(true), in: nil, contentWorld: w)
        let tap = """
        (function(){ var e=document.querySelector('h1'); var r=e.getBoundingClientRect();
          var o={bubbles:true,clientX:r.left+20,clientY:r.top+20,pointerId:1};
          e.dispatchEvent(new PointerEvent('pointerdown',o)); e.dispatchEvent(new PointerEvent('pointerup',o)); })()
        """
        // The page's own world cannot trigger anything: it has neither the handler nor the test flag.
        _ = try await web.evaluateJavaScript(tap)
        XCTAssertTrue(h.bodies.isEmpty, "a synthetic event from the page itself is not a finger")
        _ = try await web.evaluateJavaScript("window.__orchTest = true;", in: nil, contentWorld: w)   // the test plays the finger
        _ = try await web.evaluateJavaScript(tap, in: nil, contentWorld: w)
        let r = try XCTUnwrap(AnchorMaker.html(fromScript: try XCTUnwrap(h.bodies.first)))
        XCTAssertEqual(r.anchor.selector, "#hero > h1:nth-of-type(1)")
        XCTAssertEqual(r.anchor.quote, "Good things")
        XCTAssertEqual(r.anchor.viewportW, 390)
        // pins are drawn inside the page and a tap on one posts "edit"
        _ = try await web.evaluateJavaScript(AnchorScript.setPins([PinDraftItem(n: 1, anchor: r.anchor, place: r.place)]), in: nil, contentWorld: w)
        let n = try await web.evaluateJavaScript("document.querySelectorAll('[data-orch-pin]').length") as? Int
        XCTAssertEqual(n, 1)
        _ = try await web.evaluateJavaScript("document.querySelector('[data-orch-pin]').click()", in: nil, contentWorld: w)
        XCTAssertEqual((h.bodies.last as? [String: Any])?["kind"] as? String, "edit")
        // "Add comment here" posts an anchor for the middle of the screen
        let before = h.bodies.count
        _ = try await web.evaluateJavaScript("window.__orch.placeCenter();", in: nil, contentWorld: w)
        XCTAssertEqual(h.bodies.count, before + 1)
        XCTAssertNotNil(AnchorMaker.html(fromScript: h.bodies.last as Any))
        // outside comment mode nothing is posted
        let count = h.bodies.count
        _ = try await web.evaluateJavaScript(AnchorScript.setMode(false), in: nil, contentWorld: w)
        _ = try await web.evaluateJavaScript(tap, in: nil, contentWorld: w)
        XCTAssertEqual(h.bodies.count, count)
    }
}

// MARK: Info grouping, download cap, QuickLook names

final class M3HelperTests: XCTestCase {
    func testInfoGroupsAreSplitDeduplicatedAndNewestFirst() {
        let conv = ConversationID.topic(workspace: "ws_1", ticket: "t_1")
        var photo = ConvItem(id: "m1", at: "2026-11-05T10:00:00Z", side: .me)
        photo.attachments = [MessageAttachment(blobId: "b_1", kind: .image, name: "a.jpg", size: 10, mime: "image/jpeg"),
                             MessageAttachment(blobId: "b_2", kind: .file, name: "r.pdf", size: 20, mime: "application/pdf"),
                             MessageAttachment(blobId: "b_v", kind: .voice, name: "v.m4a", size: 5, mime: "audio/m4a")]
        let ticket: [TicketSnapshot.Attachment] = [
            .init(kind: "image", blobId: "b_1", name: "a.jpg", size: 10, at: "2026-11-05T11:00:00Z"),      // same blob as the message: once
            .init(kind: "html", title: "Page", url: "https://x.example/f/a#k=b", at: "2026-11-05T12:00:00Z", artifactId: "a_1", rev: "r"),
            .init(kind: "link", title: "Doc", url: "https://docs.example/x", at: "2026-11-05T09:00:00Z"),
            .init(kind: "pr", title: "PR 1", url: "https://github.com/x/1", at: "2026-11-05T08:00:00Z")]
        let all = InfoGrouping.entries(messages: [photo], ticketAttachments: ticket, ticketAt: "", conversation: conv)
        XCTAssertEqual(InfoGrouping.entries(in: .photos, from: all).count, 1)
        XCTAssertEqual(InfoGrouping.entries(in: .files, from: all).map(\.item.name), ["r.pdf"], "voice notes are not listed")
        XCTAssertEqual(InfoGrouping.entries(in: .links, from: all).map(\.item.title), ["Doc"])
        XCTAssertEqual(InfoGrouping.entries(in: .artifacts, from: all).map(\.item.title), ["Page", "PR 1"], "newest first")
    }
    func testClosingTheViewerCancelsTheDownload() async throws {
        let c = try json("publish-blob-v1")["good"] as! [String: Any]
        let link = PublishLink(URL(string: "https://p.example.org/f/x1\(c["url_fragment"] as! String)")!)!
        StubURLProtocol.hang = true; StubURLProtocol.stopped = 0; StubURLProtocol.started = 0
        defer { StubURLProtocol.hang = false }
        let cfg = URLSessionConfiguration.ephemeral; cfg.protocolClasses = [StubURLProtocol.self]
        let fetcher = PublishFetcher(session: URLSession(configuration: cfg))
        let task = Task { try await fetcher.load(link) }
        // wait until the request is really in flight (slow CI simulators), then cancel
        for _ in 0..<100 where StubURLProtocol.started == 0 { try await Task.sleep(for: .milliseconds(50)) }
        XCTAssertEqual(StubURLProtocol.started, 1, "the download started")
        task.cancel()
        do { _ = try await task.value; XCTFail("cancelled") } catch { XCTAssertTrue(error is CancellationError, "\(error)") }
        // URLSession calls stopLoading on its own queue, shortly after the cancel
        for _ in 0..<100 where StubURLProtocol.stopped == 0 { try await Task.sleep(for: .milliseconds(50)) }
        XCTAssertEqual(StubURLProtocol.stopped, 1, "the data task was cancelled, not left running")
    }
    func testDownloadIsCapped() async throws {
        let c = try json("publish-blob-v1")["good"] as! [String: Any]
        let link = PublishLink(URL(string: "https://p.example.org/f/x1\(c["url_fragment"] as! String)")!)!
        StubURLProtocol.respond = { _ in (200, Data(repeating: 1, count: 4096)) }
        let cfg = URLSessionConfiguration.ephemeral; cfg.protocolClasses = [StubURLProtocol.self]
        var f = PublishFetcher(session: URLSession(configuration: cfg)); f.maxBytes = 1000
        do { _ = try await f.load(link); XCTFail("over the cap") } catch { XCTAssertEqual(error as? PublishError, .broken) }
        XCTAssertEqual(PublishFetcher.maxBlobBytes, 100 * 1_048_576 + 65_536 + 36)
    }
    func testAgentLinksOpenOnlyAsWebAddresses() {
        func link(_ raw: String) -> ArtifactItem { ArtifactItem(TicketSnapshot.Attachment(kind: "pr", title: "PR", url: raw)) }
        XCTAssertNotNil(link("https://github.com/x/pull/1").safeLinkURL)
        XCTAssertNotNil(link("http://example.org/a").safeLinkURL)
        for bad in ["javascript:alert(1)", "tel:+41000000", "sms:+41000000", "orch://pair?code=x", "myapp://open", "file:///etc/passwd", "https:///nohost", "mailto:a@b.c"] {
            XCTAssertNil(link(bad).safeLinkURL, bad)
        }
    }
    func testPreviewIsDecidedOnTheSanitizedName() {
        let long = String(repeating: "a", count: 120) + ".pdf"      // cut to 100 characters: the extension is gone
        XCTAssertFalse(ArtifactItem.canPreview(fileName: Outbox.safeFileName(long)) )
        XCTAssertFalse(ArtifactItem.previewName(long).previewable)
        XCTAssertEqual(ArtifactItem.previewName("../.hidden/report.pdf").safe, "hidden" + "report.pdf")
        XCTAssertTrue(ArtifactItem.previewName("../report.pdf").previewable)
        XCTAssertFalse(ArtifactItem.previewName("x.pdf/..html").previewable)
    }
    func testOnlyInertTypesArePreviewedInTheApp() {
        for ok in ["report.pdf", "PHOTO.JPG", "a.png", "n.txt", "d.csv", "x.json", "v.mov", "s.m4a"] { XCTAssertTrue(ArtifactItem.canPreview(fileName: ok), ok) }
        for no in ["page.html", "logo.svg", "run.js", "noextension", "x.webarchive", "d.docx", "d.xlsx", "d.pptx", "a.zip", "n.pages", "k.key", "t.rtf"] {
            XCTAssertFalse(ArtifactItem.canPreview(fileName: no), no)
        }
    }
}

/// A loopback HTTP host that answers every request with 200 and counts connections (the page sandbox test must never reach it).
final class LoopbackHost: @unchecked Sendable {
    private let listener: NWListener
    private let lock = NSLock()
    private var count = 0
    var port: UInt16 { listener.port?.rawValue ?? 0 }
    var connections: Int { lock.lock(); defer { lock.unlock() }; return count }
    private init(_ l: NWListener) { listener = l }
    static func start() async throws -> LoopbackHost {
        let host = LoopbackHost(try NWListener(using: .tcp, on: .any))
        host.listener.newConnectionHandler = { c in
            host.lock.lock(); host.count += 1; host.lock.unlock()
            c.start(queue: .global())
            c.receive(minimumIncompleteLength: 1, maximumLength: 4096) { _, _, _, _ in
                let body = "HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
                c.send(content: Data(body.utf8), completion: .contentProcessed { _ in c.cancel() })
            }
        }
        await withCheckedContinuation { (k: CheckedContinuation<Void, Never>) in
            nonisolated(unsafe) var resumed = false
            host.listener.stateUpdateHandler = { state in
                if case .ready = state, !resumed { resumed = true; k.resume() }
            }
            host.listener.start(queue: .global())
        }
        return host
    }
    func stop() { listener.cancel() }
}
