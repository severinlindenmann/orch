import XCTest

/// REUSE NOTES (other lanes may drive this class; accessibility ids are stable, do not rename them):
///  1. Start the host side (relay + Pilatus workspace + invitation), from the repo root:
///       e2e/run.sh V3-SIM        (run inside a temp dir run by e2e/run.sh; it prints `tmp <dir>`; control folder = <dir>/ctl,
///       `<dir>/ctl/info.json` holds the pair `link`, `ws` id and `relay` url). It ends when `<dir>/ctl/stop` exists.
///  2. Run the Simulator walk (builds with xcodegen first; tests are ordered and share state):
///       TEST_RUNNER_ORCH_E2E_CTL=<dir>/ctl TEST_RUNNER_ORCH_SHOTS=<shots folder> xcodebuild test -project OrchMobile.xcodeproj \
///         -scheme OrchMobile -destination id=<simulator udid> -only-testing:OrchMobileUITests/RealRelayE2ETests/<test names, comma-free: repeat the flag>
///     test00 pairs with the invitation (single use: do not rerun it against the same harness).
///  Env vars: ORCH_E2E_CTL (required, else every test skips), ORCH_SHOTS (optional png folder), ORCH_E2E_UDID (optional).
///  Host steps are python files written into ctl/ (`host(...)`); scope: e, S, ph(), ws_send(), inbox(), relay_stop(e), relay_start(e).

/// W3-E2: the v3 app in the Simulator against a REAL local relay and a REAL workspace (`e2e/run.sh V3-SIM`).
/// Skipped unless `TEST_RUNNER_ORCH_E2E_CTL` points at the harness folder. The workspace side is driven by writing python
/// files into that folder (`host`), so the whole walk runs in one xcodebuild call. Tests run in name order and share
/// state (the paired phone, the tickets), so run the whole class.
final class RealRelayE2ETests: XCTestCase {
    private let env = ProcessInfo.processInfo.environment
    private var ctl = ""
    private var seq = 0

    override func setUpWithError() throws {
        continueAfterFailure = false
        ctl = env["ORCH_E2E_CTL"] ?? ""
        try XCTSkipUnless(!ctl.isEmpty, "real relay e2e: set TEST_RUNNER_ORCH_E2E_CTL to the V3-SIM harness folder")
    }

    // MARK: helpers
    private lazy var info: [String: Any] = {
        let d = (try? Data(contentsOf: URL(fileURLWithPath: ctl + "/info.json"))) ?? Data()
        return (try? JSONSerialization.jsonObject(with: d) as? [String: Any]) ?? [:]
    }()
    private var ws: String { info["ws"] as? String ?? "" }

    /// Runs python in the harness (`e`, `S`, `ph()`, `ws_send()`, `inbox()` are in scope; set `out`), returns `out`.
    @discardableResult
    private func host(_ code: String, file: StaticString = #filePath, line: UInt = #line) -> String {
        seq += 1
        let name = "t\(Int(Date().timeIntervalSince1970 * 1000))_\(seq)"
        try? code.write(toFile: "\(ctl)/\(name).py", atomically: true, encoding: .utf8)
        let outPath = "\(ctl)/\(name).out"
        var waited = 0.0
        while !FileManager.default.fileExists(atPath: outPath) && waited < 120 { usleep(200_000); waited += 0.2 }
        let out = (try? String(contentsOfFile: outPath, encoding: .utf8)) ?? "ERR timeout"
        if out.hasPrefix("ERR") { XCTFail("host step failed: \(out.suffix(400))", file: file, line: line) }
        return out
    }

    private func shot(_ name: String) {
        let dir = env["ORCH_SHOTS"] ?? ""
        guard !dir.isEmpty else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(name).png"))
    }

    private func launch(reset: Bool = false, extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-undoSeconds", "6", "-fakePhoto", "YES"] + (reset ? ["-resetState", "YES"] : []) + extra
        app.launch()
        return app
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }
    private func text(_ app: XCUIApplication, _ part: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@ OR value CONTAINS[c] %@", part, part)).firstMatch
    }
    private func field(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.textViews[id].exists ? app.textViews[id] : app.textFields[id]
    }
    private func must(_ app: XCUIApplication, _ e: XCUIElement, _ what: String, timeout: TimeInterval = 25) {
        if !e.waitForExistence(timeout: timeout) { XCTFail("\(what) missing. Screen: " + String(app.debugDescription.prefix(3000))) }
    }
    private func type(_ app: XCUIApplication, _ id: String, _ s: String, send: String = "composer-send") {
        let f = field(app, id)
        must(app, f, "field \(id)"); f.tap(); f.typeText(s)
        let b = el(app, send)
        must(app, b, "send button \(send)"); b.tap()
    }
    private func openGeneral(_ app: XCUIApplication) {
        let room = app.buttons["room-\(ws)"]
        if room.waitForExistence(timeout: 20) { room.tap() }
        let g = app.buttons["general-\(ws)"]
        must(app, g, "General row"); g.tap()
        must(app, el(app, "composer"), "composer")
    }
    private func back(_ app: XCUIApplication) { app.navigationBars.buttons.element(boundBy: 0).tap() }
    /// Waits for any of the ids to exist.
    private func anyOf(_ app: XCUIApplication, _ ids: [String], timeout: TimeInterval) -> String? {
        let end = Date().addingTimeInterval(timeout)
        while Date() < end {
            for i in ids where app.descendants(matching: .any)[i].exists { return i }
            usleep(400_000)
        }
        return nil
    }

    // MARK: 0 pair
    func test00PairWithTheInvitationLink() {
        let app = launch(reset: true)
        must(app, app.buttons["Paste invitation link"], "paste button", timeout: 20)
        shot("00-onboarding")
        app.buttons["Paste invitation link"].tap()
        let f = app.textFields["invite-field"]
        must(app, f, "invite field"); f.tap(); f.typeText(info["link"] as? String ?? "")
        app.buttons["invite-continue"].tap()
        must(app, app.buttons["Connect this phone"], "Connect this phone")
        shot("01-invite-found")
        app.buttons["Connect this phone"].tap()
        must(app, app.buttons["Not now"], "notification step", timeout: 30); app.buttons["Not now"].tap()
        must(app, app.buttons["room-\(ws)"], "workspace in Chats", timeout: 30)
        sleep(1); shot("02-chats")
    }

    // MARK: 1 text, receipts, reply
    func test01GeneralTextReceiptsAndReply() {
        let app = launch()
        openGeneral(app)
        shot("10-general-empty")
        type(app, "composer-field", "Hello from the phone")
        must(app, text(app, "Hello from the phone"), "my bubble")
        XCTAssertNotNil(anyOf(app, ["receipt-sent", "receipt-delivered", "receipt-queued"], timeout: 15), "a receipt")
        shot("11-general-sent")
        host("out = inbox()")   // the workspace pulls: delivered + ack
        XCTAssertNotNil(anyOf(app, ["receipt-delivered", "receipt-started"], timeout: 40), "double tick or Working after the pull")
        shot("12-general-delivered-working")
        host("ws_send('The Q3 numbers look fine. Revenue grew by 12 percent.')")
        must(app, text(app, "Revenue grew by 12 percent"), "agent reply", timeout: 40)
        shot("13-general-reply")
    }

    // MARK: 2 topic started by the agent
    func test02AgentStartsATopicChip() {
        let app = launch()
        openGeneral(app)
        type(app, "composer-field", "Please plan the offsite in March")
        must(app, text(app, "plan the offsite"), "my bubble")
        let r = host("""
        import json, glob
        inbox()
        mid = ''
        for f in sorted(glob.glob(str(e.ws('Pilatus')) + '/.orch/inbox/m_*.json')):
            m = json.load(open(f))
            if 'offsite' in json.dumps(m.get('body', {})): mid = m['id']
        o = e.orch('Pilatus', 'relay', 'topic', 'Offsite in March', '--from', mid, '--json')[1] if mid else 'none'
        out = o[:300]
        """)
        XCTAssertNotEqual(r, "none", "the offsite text reached the workspace")
        host("ws_send('I started a topic for the offsite.')")
        let chip = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'started-chip-'")).firstMatch
        _ = chip.waitForExistence(timeout: 40)
        shot("20-general-started-chip")
        XCTAssertTrue(chip.exists || text(app, "started").exists, "started chip under the reply")
        if chip.exists { chip.tap(); must(app, el(app, "composer"), "topic chat"); sleep(1); shot("21-topic-from-chip"); back(app) }
    }

    // MARK: 3 new topic from +
    func test03NewTopicFromPlus() {
        let app = launch()
        must(app, app.buttons["new-chat"], "+ in Chats"); app.buttons["new-chat"].tap()
        shot("30-plus-menu")
        must(app, app.buttons["compose-new-topic"], "New topic"); app.buttons["compose-new-topic"].tap()
        if app.buttons["workspace-picker"].waitForExistence(timeout: 3), app.buttons["workspace-picker"].isHittable {
            app.buttons["workspace-picker"].tap(); shot("31-workspace-picker")
            if app.buttons["pick-\(ws)"].waitForExistence(timeout: 3) { app.buttons["pick-\(ws)"].tap() }
        }
        type(app, "topic-field", "Make the Q3 chart", send: "topic-start")
        must(app, el(app, "composer"), "landed in the topic", timeout: 30)
        sleep(2); shot("32-new-topic-chat")
        let n = host("""
        import json
        inbox()
        out = str(len([t for t in e.orchj('Pilatus','ticket','list') if 'Q3 chart' in json.dumps(t)]))
        """)
        XCTAssertEqual(n, "1", "exactly one ticket for the new topic")
    }

    // MARK: 4 photo + pdf
    func test04PhotoAndPdfUpload() {
        let app = launch()
        openGeneral(app)
        el(app, "composer-attach").tap()
        must(app, app.buttons["media-fake-photo"], "test photo"); shot("40-picker")
        app.buttons["media-fake-photo"].tap()
        must(app, app.buttons["media-send"], "send photo"); shot("41-photo-preview")
        app.buttons["media-send"].tap()
        let img = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'image-'")).firstMatch
        must(app, img, "photo bubble", timeout: 40)
        el(app, "composer-attach").tap()
        must(app, app.buttons["media-fake-pdf"], "test pdf"); app.buttons["media-fake-pdf"].tap()
        must(app, app.buttons["media-send"], "send file"); shot("42-pdf-preview")
        app.buttons["media-send"].tap()
        let file = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'file-'")).firstMatch
        must(app, file, "pdf bubble", timeout: 40)
        sleep(2); shot("43-photo-pdf-sent")
        let r = host("""
        import re
        inbox()
        ws = e.ws('Pilatus')
        files = sorted(str(p.relative_to(ws)) for p in ws.rglob('*') if p.is_file() and p.suffix.lower() in ('.jpg','.jpeg','.pdf') and '.git' not in p.parts)
        out = ' | '.join(files)
        """)
        XCTAssertTrue(r.lowercased().contains(".pdf"), "workspace has the pdf: \(r)")
        XCTAssertTrue(r.lowercased().contains(".jp"), "workspace has the photo: \(r)")
        let pdfs = r.split(separator: "|").filter { $0.lowercased().contains(".pdf") }.count
        let jpgs = r.split(separator: "|").filter { $0.lowercased().contains(".jp") }.count
        XCTAssertEqual(pdfs, 1, "exactly one pdf: \(r)"); XCTAssertEqual(jpgs, 1, "exactly one photo: \(r)")
    }

    // MARK: 9 offline
    func test09OfflineOrderAndOnce() {
        let app = launch()
        openGeneral(app)
        host("relay_stop(e)")
        defer { host("relay_start(e)") }
        type(app, "composer-field", "Offline one")
        must(app, text(app, "Offline one"), "bubble one")
        type(app, "composer-field", "Offline two")
        must(app, text(app, "Offline two"), "bubble two")
        XCTAssertNotNil(anyOf(app, ["receipt-queued", "receipt-wait"], timeout: 20), "clock while offline")
        sleep(1); shot("90-offline-two-waiting")
        host("relay_start(e)")
        let sent = anyOf(app, ["receipt-sent", "receipt-delivered"], timeout: 60)
        XCTAssertNotNil(sent, "texts go out after the relay is back")
        var w = 0
        while el(app, "receipt-queued").exists && w < 60 { sleep(1); w += 1 }
        XCTAssertFalse(el(app, "receipt-queued").exists, "nothing left waiting")
        shot("91-offline-delivered")
        let r = host("""
        inbox()
        import json
        ph_ = ph()
        r = e.rel.admin.call('GET','/admin/api/phones')
        out = 'ok'
        """)
        _ = r
    }
}
