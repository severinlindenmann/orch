import XCTest
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
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let (code, data) = Self.respond(request)
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
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

    func testPageCannotReachTheNetworkOrUseWebRTC() async throws {
        let html = """
        <body><script>
        var r = {}; window.__r = r;
        fetch('https://127.0.0.1:9/x').then(function(){ r.fetch = 'ok'; }, function(){ r.fetch = 'blocked'; });
        var x = new XMLHttpRequest(); x.open('GET', 'https://127.0.0.1:9/x'); x.onload = function(){ r.xhr = 'ok'; }; x.onerror = function(){ r.xhr = 'blocked'; }; x.send();
        try { var w = new WebSocket('wss://127.0.0.1:9/x'); w.onopen = function(){ r.ws = 'ok'; }; w.onerror = function(){ r.ws = 'blocked'; }; } catch (e) { r.ws = 'blocked'; }
        var i = new Image(); i.onload = function(){ r.img = 'ok'; }; i.onerror = function(){ r.img = 'blocked'; }; i.src = 'https://127.0.0.1:9/p.png';
        r.rtc = (typeof RTCPeerConnection === 'undefined' && typeof webkitRTCPeerConnection === 'undefined') ? 'gone' : 'present';
        </script></body>
        """
        let (web, _, _) = try await open(html)
        var result: [String: String] = [:]
        for _ in 0..<50 {
            let json = try await web.evaluateJavaScript("JSON.stringify(window.__r || {})") as? String ?? "{}"
            result = (try? JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: String]) ?? [:]
            if result.count == 5 { break }
            try await Task.sleep(for: .milliseconds(200))
        }
        XCTAssertEqual(result, ["fetch": "blocked", "xhr": "blocked", "ws": "blocked", "img": "blocked", "rtc": "gone"])
    }

    func testTapInCommentModePostsSelectorQuoteOffset() async throws {
        let h = Handler()
        let (web, _, _) = try await open("<meta name=viewport content='width=device-width'><body style='margin:0'><section id=hero><h1 style='margin:0;height:200px'>Good things</h1></section><p>Second paragraph</p></body>", handler: h)
        let w = AnchorScript.world
        _ = try await web.evaluateJavaScript("window.__orchTest = true;", in: nil, contentWorld: w)
        _ = try await web.evaluateJavaScript(AnchorScript.setMode(true), in: nil, contentWorld: w)
        let tap = """
        (function(){ var e=document.querySelector('h1'); var r=e.getBoundingClientRect();
          var o={bubbles:true,clientX:r.left+20,clientY:r.top+20,pointerId:1};
          e.dispatchEvent(new PointerEvent('pointerdown',o)); e.dispatchEvent(new PointerEvent('pointerup',o)); })()
        """
        // The page's own world cannot trigger anything: it has neither the handler nor the test flag.
        _ = try await web.evaluateJavaScript(tap)
        XCTAssertTrue(h.bodies.isEmpty, "a synthetic event from the page itself is not a finger")
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
    func testDownloadIsCapped() async throws {
        let c = try json("publish-blob-v1")["good"] as! [String: Any]
        let link = PublishLink(URL(string: "https://p.example.org/f/x1\(c["url_fragment"] as! String)")!)!
        StubURLProtocol.respond = { _ in (200, Data(repeating: 1, count: 4096)) }
        let cfg = URLSessionConfiguration.ephemeral; cfg.protocolClasses = [StubURLProtocol.self]
        var f = PublishFetcher(session: URLSession(configuration: cfg)); f.maxBytes = 1000
        do { _ = try await f.load(link); XCTFail("over the cap") } catch { XCTAssertEqual(error as? PublishError, .broken) }
        XCTAssertEqual(PublishFetcher.maxBlobBytes, 100 * 1_048_576 + 65_536 + 36)
    }
    func testQuickLookOpensPagesAsText() {
        XCTAssertEqual(ArtifactItem.quickLookName("page.HTML"), "page.HTML.txt")
        XCTAssertEqual(ArtifactItem.quickLookName("logo.svg"), "logo.svg.txt")
        XCTAssertEqual(ArtifactItem.quickLookName("report.pdf"), "report.pdf")
    }
}
