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
    func testNetworkBlockRulesCompile() async throws {
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

// MARK: The injected script really anchors a tap (WKWebView, no network)

@MainActor
final class AnchorScriptTests: XCTestCase {
    final class Handler: NSObject, WKScriptMessageHandler {
        var bodies: [Any] = []
        func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) { bodies.append(m.body) }
    }
    final class Nav: NSObject, WKNavigationDelegate {
        var done: CheckedContinuation<Void, Never>?
        func webView(_ w: WKWebView, didFinish n: WKNavigation!) { done?.resume(); done = nil }
    }

    func testTapInCommentModePostsSelectorQuoteOffset() async throws {
        let h = Handler(), nav = Nav()
        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(h, name: AnchorScript.handler)
        cfg.userContentController.addUserScript(WKUserScript(source: AnchorScript.source, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        let web = WKWebView(frame: CGRect(x: 0, y: 0, width: 390, height: 600), configuration: cfg)
        web.navigationDelegate = nav
        await withCheckedContinuation { c in
            nav.done = c
            web.loadHTMLString("<body style='margin:0'><section id=hero><h1 style='margin:0;height:200px'>Good things</h1></section><p>Second paragraph</p></body>", baseURL: nil)
        }
        _ = try await web.evaluateJavaScript(AnchorScript.setMode(true))
        _ = try await web.evaluateJavaScript("""
        (function(){ var e=document.querySelector('h1'); var r=e.getBoundingClientRect();
          var o={bubbles:true,clientX:r.left+20,clientY:r.top+20,pointerId:1};
          e.dispatchEvent(new PointerEvent('pointerdown',o)); e.dispatchEvent(new PointerEvent('pointerup',o)); })()
        """)
        let r = try XCTUnwrap(AnchorMaker.html(fromScript: try XCTUnwrap(h.bodies.first)))
        XCTAssertEqual(r.anchor.selector, "#hero > h1:nth-of-type(1)")
        XCTAssertEqual(r.anchor.quote, "Good things")
        XCTAssertEqual(r.anchor.viewportW, 390)
        // pins are drawn inside the page and a tap on one posts "edit"
        _ = try await web.evaluateJavaScript(AnchorScript.setPins([PinDraftItem(n: 1, anchor: r.anchor, place: r.place)]))
        let n = try await web.evaluateJavaScript("document.querySelectorAll('[data-orch-pin]').length") as? Int
        XCTAssertEqual(n, 1)
        _ = try await web.evaluateJavaScript("document.querySelector('[data-orch-pin]').click()")
        XCTAssertEqual((h.bodies.last as? [String: Any])?["kind"] as? String, "edit")
        // outside comment mode nothing is posted
        let count = h.bodies.count
        _ = try await web.evaluateJavaScript(AnchorScript.setMode(false))
        _ = try await web.evaluateJavaScript("(function(){var e=document.querySelector('p');var o={bubbles:true,clientX:5,clientY:300,pointerId:1};e.dispatchEvent(new PointerEvent('pointerdown',o));e.dispatchEvent(new PointerEvent('pointerup',o));})()")
        XCTAssertEqual(h.bodies.count, count)
    }
}
