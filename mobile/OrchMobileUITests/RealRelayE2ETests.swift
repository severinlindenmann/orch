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
///  DEBUG launch arg for drivers: `-open general:<ws> | topic:<ws>:<ticket> | workspace:<ws> | settings:chats | archived`
///  navigates straight to that screen after launch (release builds ignore it; `archived` is ignored until the archive list exists).
///  Tests 12-16 reuse the paired phone and require harness helpers mm_on/mm_off/mm_status/keeper_pid/ask_question/mk_done_topic; test14 needs ORCH_E2E_SLOW=1.
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
        if !e.waitForExistence(timeout: timeout) {
            shot("fail-" + what.filter { $0.isLetter || $0.isNumber })
            XCTFail("\(what) missing. Screen: " + String(app.debugDescription.prefix(3000)))
        }
    }
    private func type(_ app: XCUIApplication, _ id: String, _ s: String, send: String = "composer-send") {
        let f = field(app, id)
        must(app, f, "field \(id)"); f.tap(); f.typeText(s)
        let b = el(app, send)
        must(app, b, "send button \(send)"); b.tap()
    }
    private func openGeneral(_ app: XCUIApplication) {
        let g = app.buttons["general-\(ws)"]
        if !g.waitForExistence(timeout: 4) {   // the app may have kept its place inside the workspace
            let room = app.buttons["room-\(ws)"]
            if room.waitForExistence(timeout: 20) { room.tap() }
        }
        must(app, g, "General row"); g.tap()
        must(app, el(app, "composer"), "composer")
    }
    /// Scrolls the list up until the element exists (long topic lists).
    private func scrollTo(_ app: XCUIApplication, _ e: XCUIElement) {
        var n = 0
        while !e.exists && n < 6 { app.swipeUp(); n += 1 }
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
        if app.buttons["Use invitation"].exists { app.buttons["Use invitation"].tap() }
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
        if mid: ws_send('I started a topic for the offsite.', '--reply-to', mid)
        """)
        XCTAssertNotEqual(r, "none", "the offsite text reached the workspace")
        let chip = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'started-chip-'")).firstMatch
        _ = chip.waitForExistence(timeout: 40)
        shot("20-general-started-chip")
        XCTAssertTrue(chip.exists || text(app, "started").exists, "started chip under the reply")
        if chip.exists {
            chip.tap(); must(app, el(app, "composer"), "topic chat")
            must(app, text(app, "plan the offsite"), "the text that started the topic, first in the topic")
            must(app, text(app, "I started a topic for the offsite"), "the agent's reply inside the topic")
            sleep(1); shot("21-topic-from-chip"); back(app); back(app)
            let row = app.buttons["room-\(ws)"]
            must(app, row, "Chats row")
            sleep(1); shot("22-chats-rows")
            XCTAssertTrue(row.label.localizedCaseInsensitiveContains("offsite"), "row shows the last line: \(row.label)")
            XCTAssertTrue(row.label.range(of: "[0-9]{1,2}:[0-9]{2}|Yesterday|[A-Z][a-z]{2} ", options: .regularExpression) != nil, "row shows a time: \(row.label)")
        }
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
        let title = "Make the Q3 chart \(Int(Date().timeIntervalSince1970) % 100000)"
        type(app, "topic-field", title, send: "topic-start")
        must(app, text(app, "Getting started"), "Starting topic row in the workspace", timeout: 30)
        shot("32-starting-topic")
        host("out = inbox()")   // the workspace pulls and makes the ticket + ack: the topic opens by itself or shows as a row
        let opened = el(app, "composer").waitForExistence(timeout: 30)
        sleep(2); shot("33-new-topic-after-ack")
        let n = host("""
        import json
        out = str(len([t for t in e.orchj('Pilatus','ticket','list') if '\(title)' in t.get('title','')]))
        """)
        XCTAssertEqual(n, "1", "exactly one ticket for the new topic")
        XCTAssertTrue(opened || text(app, "Make the Q3 chart").exists, "the new topic opened or is listed")
    }

    // MARK: 4 photo + pdf
    func test04PhotoAndPdfUpload() {
        let countCode = """
        ws = e.ws('Pilatus')
        out = ' | '.join(sorted(str(p.relative_to(ws)) for p in ws.rglob('*') if p.is_file() and p.suffix.lower() in ('.jpg','.jpeg','.pdf') and '.git' not in p.parts))
        """
        let beforeFiles = Set(host(countCode).split(separator: "|").map { $0.trimmingCharacters(in: .whitespaces) })
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
        sleep(1)   // a file goes out at once, there is no preview step
        let file = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'file-'")).firstMatch
        must(app, file, "pdf bubble", timeout: 40)
        sleep(2); shot("43-photo-pdf-sent")
        host("out = inbox()")
        let now = Set(host(countCode).split(separator: "|").map { $0.trimmingCharacters(in: .whitespaces) })
        let added = now.subtracting(beforeFiles).filter { !$0.isEmpty }
        let pdfs = added.filter { $0.lowercased().hasSuffix(".pdf") }.count
        let jpgs = added.filter { $0.lowercased().hasSuffix(".jpg") || $0.lowercased().hasSuffix(".jpeg") }.count
        XCTAssertEqual(pdfs, 1, "exactly one new pdf in the workspace: \(added)")
        XCTAssertEqual(jpgs, 1, "exactly one new photo in the workspace: \(added)")
    }

    // MARK: 5 location
    func test05LocationCard() {
        let udid = env["ORCH_E2E_UDID"] ?? "booted"
        host("""
        import subprocess
        subprocess.run(['xcrun','simctl','privacy','\(udid)','grant','location','io.severin.orch'])
        out = subprocess.run(['xcrun','simctl','location','\(udid)','set','47.0502,8.3093'], capture_output=True, text=True).stderr[:200]
        """)
        let app = launch()
        openGeneral(app)
        el(app, "composer-attach").tap()
        must(app, app.buttons["media-location"], "Location tile"); app.buttons["media-location"].tap()
        let send = app.buttons["media-send"]
        let alert = XCUIApplication(bundleIdentifier: "com.apple.springboard").alerts.buttons["Allow While Using App"]
        if alert.waitForExistence(timeout: 5) { alert.tap() }
        if !send.waitForExistence(timeout: 20) { shot("50-location-problem") }
        must(app, send, "Share current location", timeout: 5); shot("51-location-preview")
        send.tap()
        let card = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'location-'")).firstMatch
        must(app, card, "location card", timeout: 30)
        sleep(1); shot("52-location-card")
        XCTAssertLessThanOrEqual(card.frame.maxX, app.windows.firstMatch.frame.width + 1, "the location card must not be wider than the screen")
        let hist = host("""
        import json, glob
        inbox()
        hits = [json.load(open(f)) for f in sorted(glob.glob(str(e.ws('Pilatus')) + '/.orch/inbox/m_*.json'))]
        out = str([m['body'].get('location') for m in hits if m['body'].get('location')][-1:])
        """)
        XCTAssertTrue(hist.contains("47.05"), "the workspace got the location: \(hist)")
    }

    // MARK: 6 questions
    func test06QuestionAnswerAndStale() {
        let t = host("""
        import json, subprocess
        t = json.loads(e.orch('Pilatus','ticket','new','Ship it check','--json')[1])['id']
        S['qt'] = t
        S['ask'] = [subprocess.Popen(['orch','ask',t,'Shall we ship it?','--option','Yes','--option','No','--recommend','Yes','--phone'],
                    cwd=str(e.ws('Pilatus')), env=e.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
        e.pids.append(S['ask'][0].pid)
        out = t
        """)
        let app = launch(extra: ["-open", "workspace:\(ws)"])
        let row = app.buttons["ticket-\(ws)|\(t)"]
        _ = row.waitForExistence(timeout: 30); scrollTo(app, row)
        must(app, row, "ticket row of the question", timeout: 10); row.tap()
        let yes = el(app, "answer-Yes")
        must(app, yes, "answer Yes", timeout: 30); shot("60-question")
        yes.tap()
        let undo = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'undo-'")).firstMatch
        XCTAssertTrue(undo.waitForExistence(timeout: 4)); shot("61-undo")
        let answered = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'answered-'")).firstMatch
        must(app, answered, "answered card", timeout: 30); shot("62-answered")
        // second question, answered first by another phone
        host("""
        import json, subprocess
        t = S['qt']
        S['ask'].append(subprocess.Popen(['orch','ask',t,'Which colour?','--option','Red','--option','Blue','--phone'],
                    cwd=str(e.ws('Pilatus')), env=e.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        e.pids.append(S['ask'][-1].pid)
        """)
        must(app, el(app, "answer-Red"), "second question", timeout: 40)
        let r = host("""
        from lib import http
        import time
        a = e.rel.admin.call('POST','/admin/api/phones',{'name':'Second phone','workspaces':[info['ws']]}).json()
        code = a['link'].split('code=')[1]
        pj = http('POST', e.rel.url + '/v1/phone/pair', None, {'code': code, 'name': 'Second phone'}).json()
        h = {'X-Orch-Phone': pj['phone_id'], 'Authorization': 'Bearer ' + pj['token']}
        qs = http('GET', e.rel.url + '/v1/phone/questions', h).json()['items']
        q = [x for x in qs if 'colour' in x['message']['body']['text']][0]
        r = http('POST', e.rel.url + '/v1/phone/answer', h, {'question_message_id': q['message']['id'], 'answer': 'Blue', 'client_id': str(__import__('uuid').uuid4())})
        out = str(r.status) + ' ' + r.text[:200]
        """)
        XCTAssertTrue(r.hasPrefix("20"), "second phone answered: \(r)")
        el(app, "answer-Red").tap()
        sleep(3); shot("63-answered-elsewhere")
        XCTAssertTrue(text(app, "Already answered on your computer").waitForExistence(timeout: 40), "stale answer shows who answered")
        shot("64-stale-answer-note")
    }

    // MARK: 7 artifact (pdf) + feedback
    func test07ArtifactLooksGoodAndPin() {
        let tid = host(deckPython)
        let app = launch(extra: ["-open", "workspace:\(ws)"])
        let row = app.buttons["ticket-\(ws)|\(tid)"]
        // a ticket that got its result is Done: it is listed under the Done segment
        if !row.waitForExistence(timeout: 25), app.buttons["segment-done"].exists { app.buttons["segment-done"].tap() }
        _ = row.waitForExistence(timeout: 15); scrollTo(app, row)
        must(app, row, "deck ticket row", timeout: 10); row.tap()
        let card = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'artifact-'")).firstMatch
        must(app, card, "artifact card in the result bubble", timeout: 40); sleep(1); shot("70-result-card")
        card.tap()
        must(app, app.buttons["artifact-comment"], "viewer with Comment", timeout: 30); sleep(2); shot("71-viewer")
        app.buttons["artifact-comment"].tap()
        let center = app.windows.firstMatch.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.45))
        center.tap(); sleep(1); shot("72-pin-placed")
        let pt = field(app, "pin-text")
        must(app, pt, "pin text field"); pt.tap(); pt.typeText("Make the title bigger")
        el(app, "pin-save").tap(); sleep(1); shot("73-pin-saved")
        must(app, el(app, "artifact-send-comments"), "Send comments"); el(app, "artifact-send-comments").tap()
        must(app, text(app, "comment"), "my feedback bubble", timeout: 20); shot("74-feedback-sent")
        let hist = host("""
        import json
        inbox()
        from scenarios_ws import tload
        out = json.dumps(tload(e.ws('Pilatus'), S['deck']))
        """)
        XCTAssertTrue(hist.contains("Make the title bigger"), "pin text arrived in the ticket history")
        XCTAssertTrue(hist.contains("changes wanted"), "verdict words in the history")
    }

    // MARK: 8 voice
    func test08VoiceMemoAndSettings() {
        host("""
        import subprocess
        subprocess.run(['xcrun','simctl','privacy','\(env["ORCH_E2E_UDID"] ?? "booted")','grant','all','io.severin.orch'])
        """)
        let app = launch(extra: ["-fakeVoice", "YES"])
        openGeneral(app)
        // A system permission alert (speech, microphone) never blocks the test: answer it whenever it shows.
        addUIInterruptionMonitor(withDescription: "permission") { alert in
            for name in ["Allow", "OK", "Allow While Using App"] where alert.buttons[name].exists { alert.buttons[name].tap(); return true }
            return false
        }
        let mic = el(app, "composer-mic"); must(app, mic, "mic")
        XCTAssertTrue(mic.waitForExistence(timeout: 10))
        for _ in 0..<20 where !mic.isHittable { usleep(500_000) }
        mic.press(forDuration: 3.5)   // recording starts ~0.25 s after the touch and under load can take a second more; < 1 s is dropped
        must(app, el(app, "voice-play"), "my voice note bubble", timeout: 30); sleep(1); shot("80-voice-note")
        host("ws_send('Here is a long answer you can listen to instead of reading it.', '--speak')")
        let plays = app.descendants(matching: .any).matching(identifier: "voice-play")
        let end = Date().addingTimeInterval(40)
        while plays.count < 2 && Date() < end { usleep(500_000) }   // the agent's answer is a memo bubble (text behind "Show text")
        XCTAssertGreaterThanOrEqual(plays.count, 2, "the spoken answer shows as a memo bubble")
        sleep(1); shot("81-agent-memo")
        if el(app, "memo-show-text").exists { el(app, "memo-show-text").tap(); sleep(1); shot("81b-memo-text") }
        if plays.count > 0 { plays.element(boundBy: plays.count - 1).tap(); sleep(3); shot("82-memo-fallback-tts") }
        XCTAssertTrue(app.state == .runningForeground, "no crash when the speech fallback plays")
        back(app); back(app)
        el(app, "settings-button").tap()
        must(app, el(app, "voice-settings"), "Voice settings row"); el(app, "voice-settings").tap()
        sleep(1); shot("83-voice-settings")
        app.buttons["voice-replies-menu"].tap()
        if app.buttons["speak-always"].waitForExistence(timeout: 5) { app.buttons["speak-always"].tap() }
        let sw = app.switches.firstMatch
        if sw.waitForExistence(timeout: 3) { sw.tap() }
        sleep(2); shot("84-voice-settings-changed")
    }

    // MARK: 10 mute, add by invitation, remove
    func test10MuteAddAndRemoveWorkspace() {
        let link = host("""
        a = e.rel.admin.call('POST','/admin/api/phones',{'name':'Home invitation','workspaces':[ids['Home']]}).json()
        out = a['link']
        """)
        let app = launch()
        el(app, "settings-button").tap()
        must(app, el(app, "settings-ws-\(ws)"), "workspace row in Settings"); shot("100-settings")
        el(app, "settings-ws-\(ws)").tap()
        must(app, el(app, "mute-Always"), "mute options"); el(app, "mute-Always").tap(); sleep(2); shot("101-muted")
        el(app, "mute-Off").tap(); sleep(2)
        back(app)
        el(app, "add-workspace").tap()
        if app.buttons["Use invitation"].exists { app.buttons["Use invitation"].tap() }
        must(app, app.buttons["Paste invitation link"], "Paste invitation link"); app.buttons["Paste invitation link"].tap()
        let f = app.textFields["invite-field"]
        must(app, f, "invite field"); f.tap(); f.typeText(link)
        app.buttons["invite-continue"].tap()
        sleep(1); shot("102-add-found")
        let add = el(app, "invite-add")
        if add.waitForExistence(timeout: 10) { add.tap() }
        let homeId = host("out = ids['Home']")
        back(app)
        must(app, el(app, "settings-ws-\(homeId)"), "Home added", timeout: 30); shot("103-home-added")
        el(app, "settings-ws-\(homeId)").tap()
        must(app, el(app, "remove-workspace"), "remove"); el(app, "remove-workspace").tap()
        must(app, app.buttons["Remove"], "confirm remove"); shot("104-remove-confirm"); app.buttons["Remove"].tap()
        sleep(3)
        XCTAssertFalse(el(app, "settings-ws-\(homeId)").exists, "Home is gone from Settings")
        shot("105-home-removed")
    }

    // MARK: 17 workspace look
    /// The workspace picks an icon and colour (PATCH /v1/me); the chats list shows the badge `workspace-badge-<id>`.
    func test17WorkspaceIconInChatsList() {
        let r = host("""
        r = e.rapi('Pilatus', 'PATCH', '/v1/me', {'icon': 'wallet', 'color': 'amber'})
        out = str(r.status)
        """)
        XCTAssertEqual(r.trimmingCharacters(in: .whitespacesAndNewlines), "200", "workspace look saved on the relay")
        let app = launch()
        must(app, el(app, "workspace-badge-\(ws)"), "workspace badge in the chats list"); shot("170-look-chats")
        app.terminate()
    }

    // MARK: 11 the four v2 bugs
    func test11V2BugsDoNotOccur() {
        let app = launch()
        openGeneral(app)
        // badge counting the open chat: an agent text arrives while the chat is open, leaving shows no unread for it
        host("ws_send('Arrived while you are reading.')")
        must(app, text(app, "Arrived while you are reading"), "live text", timeout: 40)
        sleep(2)
        back(app)
        let g = app.buttons["general-\(ws)"]
        must(app, g, "General row")
        XCTAssertFalse(g.label.contains("unread"), "open chat counted as unread: \(g.label)")
        shot("110-no-badge-after-open-chat")
        // duplicate "created" chip: one chip per ack
        g.tap()
        let chips = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'started-chip-'"))
        sleep(2)
        var seen = Set<String>()
        for i in 0..<chips.count { XCTAssertTrue(seen.insert(chips.element(boundBy: i).identifier).inserted, "duplicate chip \(chips.element(boundBy: i).identifier)") }
        // durations: no memo or voice bubble shows 00:01 for a long note
        XCTAssertFalse(text(app, "00:01").exists, "a 00:01 duration is shown")
        // empty chat refresh: a topic with no messages pulls to refresh without turning into an error
        back(app)
        let first = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'ticket-'")).firstMatch
        if first.waitForExistence(timeout: 5) {
            first.tap(); must(app, el(app, "composer"), "topic")
            app.swipeDown(); sleep(2)
            XCTAssertFalse(text(app, "Couldn't").exists, "error after refreshing an empty chat")
            shot("111-empty-topic-refresh")
        }
    }

    private var deckPython: String { """
    import json
    t = json.loads(e.orch("Pilatus", "ticket", "new", "Board deck", "--json")[1])["id"]
    S["deck"] = t
    e.orch("Pilatus", "check", "add", t, "Make the deck")
    pdf = "%PDF-1.4|1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj|2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj|3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj|4 0 obj<</Length 44>>stream|BT /F1 24 Tf 40 100 Td (Board deck Q3) Tj ET|endstream endobj|5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj|trailer<</Root 1 0 R/Size 6>>|%%EOF|".replace("|", chr(10)).encode()
    p = e.ws("Pilatus") / "deck.pdf"; p.write_bytes(pdf)
    o = e.orch("Pilatus", "check", "done", t, "c1", "--file", str(p), "--title", "Board deck", "--role", "result")
    e.orch("Pilatus", "relay", "send", ph(), "The board deck draft is ready.", "--ticket", t, "--update", "result")
    out = t
    """ }


    // MARK: 12 mobile mode and question routing
    func test12MobileModeOnShowsBannerAndRoutesQuestion() {
        host("out = mm_on(4)")
        let app = launch()
        chats(app)
        // The banner moved off the Chats list (round-8): it sits on the workspace screen.
        openWorkspace(app)
        let banner = mobileBanner(app, containing: "Send questions to my phone · on")
        must(app, banner, "Mobile mode banner in workspace", timeout: 90)
        XCTAssertTrue(banner.label.contains("Send questions to my phone"))
        must(app, el(app, "mobile-mode-off-\(ws)"), "workspace Turn off button", timeout: 10)
        shot("121-mobile-mode-workspace")
        let ticket = host("out = ask_question('Mobile mode question?')")
        let q = launch(extra: ["-open", "workspace:\(ws)"])
        let row = el(q, "ticket-\(ws)|\(ticket)")
        _ = row.waitForExistence(timeout: 30); scrollTo(q, row)
        must(q, row, "mobile mode question ticket", timeout: 10); row.tap()
        must(q, text(q, "Mobile mode question?"), "question in chat", timeout: 60)
        must(q, el(q, "answer-Yes"), "routed question answer", timeout: 60)
        shot("122-mobile-mode-question")
    }

    // MARK: 13 turn off from the paired phone
    func test13TurnOffFromThePhone() throws {
        let app = launch()
        chats(app)
        let off = el(app, "mobile-mode-off-\(ws)")
        must(app, off, "Turn off button", timeout: 60); off.tap()
        let stateJSON = host("""
        import json, time
        t0 = time.monotonic()
        deadline = t0 + 130
        state = json.loads(mm_status())
        while state.get('on') is not False and time.monotonic() < deadline:
            time.sleep(min(5, max(0, deadline - time.monotonic())))
            state = json.loads(mm_status())
        assert state.get('on') is False, state
        S['off_secs'] = round(time.monotonic() - t0)
        assert S['off_secs'] <= 75, 'turned off only after %s s (keeper poll is 60 s)' % S['off_secs']
        out = json.dumps(state)
        """)
        let state = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(stateJSON.utf8)) as? [String: Any])
        let ended = state["ended"] as? [String: Any]
        let endedText = ended?["text"] as? String ?? ""
        XCTAssertTrue(endedText.lowercased().contains("turned off from your phone"), "Unexpected ended text: \(endedText)")
        XCTAssertTrue(el(app, "mobile-mode-banner-\(ws)").waitForNonExistence(timeout: 60), "Mobile mode banner disappears")
        host("assert keeper_pid() == '', 'keeper is still running'")
        shot("123-mobile-mode-off-from-phone")
    }

    // MARK: 14 silence threshold (opt-in slow test)
    func test14UnreachableBannerAfterFiveMinutes() throws {
        try XCTSkipUnless(env["ORCH_E2E_SLOW"] == "1", "needs the 5-minute silence threshold, hard-coded in relay/src/mobile.rs UNREACHABLE_SECS")
        host("out = mm_on(4)")
        defer {
            host("""
            import os, signal
            pid = S.pop('mobile_mode_stopped_pid', '')
            if pid:
                try: os.kill(int(pid), signal.SIGCONT)
                except ProcessLookupError: pass
            out = mm_off()
            """)
        }
        let app = launch()
        chats(app); openWorkspace(app)
        must(app, mobileBanner(app, containing: "Send questions to my phone · on"), "reachable banner", timeout: 90)
        host("""
        import os, signal
        pid = keeper_pid()
        assert pid, 'no keeper to stop'
        S['mobile_mode_stopped_pid'] = pid
        os.kill(int(pid), signal.SIGSTOP)
        """)
        must(app, mobileBanner(app, containing: "Can't reach"), "unreachable banner after silence", timeout: 480)
        shot("124-mobile-mode-unreachable")
        host("import os, signal; os.kill(int(S['mobile_mode_stopped_pid']), signal.SIGCONT)")
        must(app, mobileBanner(app, containing: "Send questions to my phone · on"), "reachable banner after resume", timeout: 90)
        host("out = mm_off()")
        XCTAssertTrue(el(app, "mobile-mode-banner-\(ws)").waitForNonExistence(timeout: 60))
        shot("125-mobile-mode-recovered-and-off")
    }

    // MARK: 15 muted workspace in mobile mode
    func test15MutedWorkspaceInMobileMode() {
        defer { host("out = mm_off()") }
        host("out = mm_on(4)")
        let app = launch()
        chats(app); openWorkspace(app)
        must(app, mobileBanner(app, containing: "Send questions to my phone · on"), "Mobile mode banner", timeout: 90)
        setMute(app, "Always"); openWorkspace(app)
        // Muting preserves Mobile mode and hides its Turn off action.
        must(app, mobileBanner(app, containing: "Send questions to my phone · muted"), "muted Mobile mode banner", timeout: 40)
        XCTAssertFalse(el(app, "mobile-mode-off-\(ws)").exists, "muted banner has no Turn off button")
        host("out = ask_question('Muted mobile mode question?')")
        // Simulator cannot observe push absence; relay tests cover suppression of pushes while muted.
        must(app, mobileBanner(app, containing: "Send questions to my phone · muted"), "muted banner after question delivery", timeout: 30)
        XCTAssertFalse(el(app, "mobile-mode-off-\(ws)").exists)
        shot("126-mobile-mode-muted-question")
        setMute(app, "Off"); openWorkspace(app)
        must(app, mobileBanner(app, containing: "Send questions to my phone · on"), "unmuted banner", timeout: 30)
        host("out = mm_off()")
        XCTAssertTrue(el(app, "mobile-mode-banner-\(ws)").waitForNonExistence(timeout: 60))
        shot("127-mobile-mode-unmuted-and-off")
    }

    // MARK: 16 archive, undo, agent unarchive and phone-only delete
    func test16ArchiveUndoArchivedListUnarchiveAndDelete() {
        let t1 = host("out = mk_done_topic('Archive me')")
        let t2 = host("out = mk_done_topic('Delete me')")
        let app = launch(extra: ["-open", "workspace:\(ws)"])
        // The workspace's Done tickets sit behind "Done (n)" on its screen (W7-BUGS 4: strict again)
        openDone(app)
        let row = el(app, "ticket-\(ws)|\(t1)")
        scrollTo(app, row)
        must(app, row, "Archive me row", timeout: 60)
        row.swipeLeft()
        must(app, app.buttons["Archive"], "Archive action", timeout: 5); app.buttons["Archive"].tap()
        must(app, el(app, "archive-toast"), "archive toast", timeout: 5)
        must(app, app.buttons["Undo"], "archive Undo", timeout: 5); app.buttons["Undo"].tap()
        must(app, row, "row restored by Undo", timeout: 10)
        row.swipeLeft()
        must(app, app.buttons["Archive"], "Archive again", timeout: 5); app.buttons["Archive"].tap()
        XCTAssertTrue(row.waitForNonExistence(timeout: 10))
        let archived = el(app, "archived-row")
        scrollTo(app, archived)
        must(app, archived, "Archived in Chats", timeout: 10)
        scrollTo(app, archived)
        archived.tap()
        must(app, el(app, "archived-t:\(ws)|\(t1)"), "archived ticket", timeout: 10)
        shot("128-archived-list")
        back(app)
        host("ws_send('Back again', '--ticket', '\(t1)')")
        // The active list refreshes on its own; the plain ticket message restores the archived chat.
        expandDone(app)

        must(app, row, "agent message unarchives ticket", timeout: 40)
        _ = launch(extra: ["-open", "workspace:\(ws)"])
        openDone(app)
        let deleted = el(app, "ticket-\(ws)|\(t2)")
        scrollTo(app, deleted)
        must(app, deleted, "Delete me row", timeout: 30); deleted.swipeLeft()
        must(app, app.buttons["Delete"], "Delete action", timeout: 5); app.buttons["Delete"].tap()
        must(app, el(app, "delete-confirm"), "delete confirmation", timeout: 5); el(app, "delete-confirm").tap()
        XCTAssertTrue(deleted.waitForNonExistence(timeout: 10), "deleted row leaves Chats")
        // If no Archived entry remains, there are no archived chats (including the deleted ticket).
        scrollTo(app, archived)
        if archived.exists {
            scrollTo(app, archived)
            archived.tap()
            must(app, app.navigationBars["Archived"], "Archived list", timeout: 10)
            XCTAssertFalse(el(app, "archived-t:\(ws)|\(t2)").exists, "deleted ticket is not archived")
            back(app)
        }
        host("rc, result, _err = e.orch('Pilatus', 'ticket', 'show', '\(t2)'); assert rc == 0, result")  // the ticket stays in the workspace
        shot("129-archive-unarchive-and-delete")
    }

    /// Done sits below the open topics: in a busy workspace it is off screen. Scroll to it, then open it.
    private func openDone(_ app: XCUIApplication) {
        let toggle = app.buttons["done-toggle"]
        let end = Date().addingTimeInterval(40)
        while !toggle.exists && Date() < end { app.swipeUp(); sleep(1) }
        must(app, toggle, "Done (n) section on the workspace screen", timeout: 5)
        expandDone(app)
    }

    /// The workspace screen keeps finished topics behind "Done (n)"; open it when it is closed.
    private func expandDone(_ app: XCUIApplication) {
        let t = app.buttons["done-toggle"]
        if t.exists, (t.value as? String) == "Collapsed" { t.tap() }
    }

    /// From the Chats list into the workspace screen (where the Mobile mode banner lives).
    private func openWorkspace(_ app: XCUIApplication) {
        let room = el(app, "room-\(ws)")
        must(app, room, "workspace row", timeout: 30); room.tap()
    }

    private func chats(_ app: XCUIApplication) {
        for _ in 0..<6 {
            if el(app, "new-chat").waitForExistence(timeout: 2) { break }
            back(app)
        }
        must(app, el(app, "new-chat"), "Chats root", timeout: 30)
    }

    /// The banner container has no label of its own: find the words in its text child (the returned element is that text).
    private func mobileBanner(_ app: XCUIApplication, containing words: String) -> XCUIElement {
        app.otherElements["mobile-mode-banner-\(ws)"].staticTexts.matching(NSPredicate(format: "label CONTAINS %@", words)).firstMatch
    }

    private func setMute(_ app: XCUIApplication, _ choice: String) {
        chats(app)
        must(app, el(app, "settings-button"), "Settings", timeout: 10); el(app, "settings-button").tap()
        must(app, el(app, "settings-ws-\(ws)"), "workspace settings", timeout: 10); el(app, "settings-ws-\(ws)").tap()
        must(app, el(app, "mute-\(choice)"), "mute \(choice)", timeout: 10); el(app, "mute-\(choice)").tap()
        chats(app)
    }
}
