import XCTest

/// ORCH-1204 step c7: signed messages in the Simulator against a REAL local relay and TWO real test workspaces
/// (Pilatus and Reports of the V3-SIM harness, `e2e/sim-run.sh start`). Skipped unless `TEST_RUNNER_ORCH_E2E_CTL`
/// points at the harness folder (see RealRelayE2ETests for the host side). One test, in order:
///   1. pair the phone for both workspaces (its own invitation, so RealRelayE2ETests keeps its own),
///   2. each workspace's first message waits behind an Accept card with that workspace's fingerprint; one Accept,
///      and it does not come back for the next message,
///   3. what the phone sends is signed and held by the workspace until a person there accepts the phone's
///      fingerprint (as shown on the phone's Settings page),
///   4. a relay that edits its stored copy: the phone shows only the signed words; edited signed bytes: the
///      message is refused and named ("changed on the way"),
///   5. the phone's answer to a signed question is signed with that question and applied by the workspace.
final class SignedTwoWorkspacesE2ETests: XCTestCase {
    private let env = ProcessInfo.processInfo.environment
    private var ctl = ""
    private var seq = 0

    override func setUpWithError() throws {
        continueAfterFailure = false
        ctl = env["ORCH_E2E_CTL"] ?? ""
        try XCTSkipUnless(!ctl.isEmpty, "real relay e2e: set TEST_RUNNER_ORCH_E2E_CTL to the V3-SIM harness folder")
    }

    @discardableResult
    private func host(_ code: String, file: StaticString = #filePath, line: UInt = #line) -> String {
        seq += 1
        let name = "s\(Int(Date().timeIntervalSince1970 * 1000))_\(seq)"
        try? code.write(toFile: "\(ctl)/\(name).py", atomically: true, encoding: .utf8)
        let outPath = "\(ctl)/\(name).out"
        var waited = 0.0
        while !FileManager.default.fileExists(atPath: outPath) && waited < 180 { usleep(200_000); waited += 0.2 }
        let out = (try? String(contentsOfFile: outPath, encoding: .utf8)) ?? "ERR timeout"
        if out.hasPrefix("ERR") { XCTFail("host step failed: \(out.suffix(600))", file: file, line: line) }
        return out
    }

    private func shot(_ name: String) {
        let dir = env["ORCH_SHOTS"] ?? ""
        guard !dir.isEmpty else { return }
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("signed-\(name).png"))
    }

    private func launch(reset: Bool = false, extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-undoSeconds", "3"] + (reset ? ["-resetState", "YES"] : []) + extra
        app.launch()
        return app
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }
    private func text(_ app: XCUIApplication, _ part: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@ OR value CONTAINS[c] %@", part, part)).firstMatch
    }
    private func must(_ app: XCUIApplication, _ e: XCUIElement, _ what: String, timeout: TimeInterval = 30) {
        if !e.waitForExistence(timeout: timeout) {
            shot("fail-" + what.filter { $0.isLetter || $0.isNumber })
            XCTFail("\(what) missing. Screen: " + String(app.debugDescription.prefix(3000)))
        }
    }
    /// Only letters and digits, lower case: fingerprints compare whatever their grouping.
    private func plain(_ s: String) -> String { s.lowercased().filter { $0.isLetter || $0.isNumber } }

    func testSignedMessagesWithTwoWorkspaces() {
        let run = String(Int(Date().timeIntervalSince1970) % 100000)   // own words per run: the harness keeps earlier runs
        // ---- host: both workspaces sign; one invitation for both
        let setup = host("""
        import json
        fp = {}
        for n in ('Pilatus', 'Reports'):
            fp[n] = json.loads(e.orch(n, 'relay', 'status', '--json')[1]).get('fingerprint') or ''
            assert fp[n], n + ' has no signing key'
        a = e.rel.admin.call('POST', '/admin/api/phones', {'name': 'Signed phone', 'workspaces': [ids['Pilatus'], ids['Reports']]})
        assert a.status == 201, a
        S['signed_fp'] = fp
        out = json.dumps({'link': a.json()['link'], 'pilatus': ids['Pilatus'], 'reports': ids['Reports'], 'fp': fp})
        """)
        guard let d = setup.data(using: .utf8), let info = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let link = info["link"] as? String, let pil = info["pilatus"] as? String, let rep = info["reports"] as? String,
              let fp = info["fp"] as? [String: String] else { return XCTFail("setup: \(setup)") }

        // ---- 1. pair for both workspaces
        var app = launch(reset: true)
        must(app, app.buttons["invite-paste"], "paste button")
        app.buttons["invite-paste"].tap()
        let f = app.textFields["invite-field"]
        must(app, f, "invite field"); f.tap(); f.typeText(link)
        app.buttons["invite-continue"].tap()
        must(app, app.buttons["Connect this phone"], "Connect this phone"); app.buttons["Connect this phone"].tap()
        must(app, app.buttons["Not now"], "notification step"); app.buttons["Not now"].tap()
        must(app, app.buttons["room-\(pil)"], "Pilatus in Chats")
        must(app, app.buttons["room-\(rep)"], "Reports in Chats")
        let ph = host("""
        import json
        items = e.rel.admin.call('GET', '/admin/api/phones').json()['items']
        out = [p['id'] for p in items if p['paired'] and ids['Reports'] in json.dumps(p.get('workspaces'))][-1]
        S['signed_ph'] = out
        """)

        // ---- 2. accept each workspace once, by its fingerprint
        for (ws, name) in [(pil, "Pilatus"), (rep, "Reports")] {
            host("e.orch('\(name)', 'relay', 'send', S['signed_ph'], 'Signed hello from \(name)')")
            app.terminate()
            app = launch(extra: ["-open", "workspace:\(ws)"])
            let shown = el(app, "accept-fingerprint")
            must(app, shown, "Accept card of \(name)", timeout: 40)
            XCTAssertEqual(plain(shown.label), plain(fp[name] ?? "-"), "the card shows \(name)'s own fingerprint")
            XCTAssertFalse(text(app, "Signed hello from \(name)").exists, "the message waits until Accept")
            shot("1-accept-\(name)")
            el(app, "accept-workspace").tap()
            XCTAssertTrue(shown.waitForNonExistence(timeout: 10), "the card goes after Accept")
            if app.buttons["general-\(ws)"].waitForExistence(timeout: 10) { app.buttons["general-\(ws)"].tap() }
            must(app, text(app, "Signed hello from \(name)"), "\(name)'s message after Accept", timeout: 40)
            shot("2-after-accept-\(name)")
        }
        // once: the next message comes without a card, also after a restart
        host("e.orch('Pilatus', 'relay', 'send', S['signed_ph'], 'Second signed message \(run)')")
        app.terminate()
        app = launch(extra: ["-open", "general:\(pil)"])
        must(app, text(app, "Second signed message \(run)"), "second message without Accept", timeout: 40)
        XCTAssertFalse(el(app, "accept-fingerprint").exists, "Accept is asked once")

        // ---- 3. the phone signs; the workspace holds it until a person accepts the phone
        let composer = app.textViews["composer-field"].exists ? app.textViews["composer-field"] : app.textFields["composer-field"]
        must(app, composer, "composer"); composer.tap(); composer.typeText("Signed words from the phone \(run)")
        el(app, "composer-send").tap()
        must(app, text(app, "Signed words from the phone \(run)"), "my bubble")
        sleep(3)
        let held = host("""
        import json, glob
        e.orch('Pilatus', 'relay', 'inbox')
        e.orch('Pilatus', 'relay', 'refresh')
        files = glob.glob(str(e.ws('Pilatus')) + '/.orch/inbox/m_*.json')
        handled = any('Signed words from the phone \(run)' in open(x).read() for x in files)
        c = [x for x in json.loads(e.orch('Pilatus', 'relay', 'contacts', 'list', '--json')[1]).get('items', []) if x.get('id') == S['signed_ph']]
        out = json.dumps({'handled': handled, 'state': c[0].get('state') if c else None, 'fp': c[0].get('fingerprint') if c else None})
        """)
        XCTAssertTrue(held.contains("\"handled\": false"), "held until the phone is accepted: \(held)")
        app.terminate()
        app = launch(extra: ["-startTab", "settings"])
        let phoneFp = el(app, "phone-fingerprint")
        for _ in 0..<6 where !phoneFp.isHittable { app.swipeUp() }
        must(app, phoneFp, "THIS PHONE fingerprint")
        shot("3-settings-phone-fingerprint")
        var label = phoneFp.label
        if let r = label.range(of: "Your workspaces") { label = String(label[..<r.lowerBound]) }
        label = label.replacingOccurrences(of: "Fingerprint", with: "").trimmingCharacters(in: CharacterSet(charactersIn: ", ").union(.whitespacesAndNewlines))
        XCTAssertTrue(held.contains(label) || plain(held).contains(plain(label)), "the workspace sees the phone's own fingerprint: \(held) vs \(label)")
        let accepted = host("""
        import json, glob
        rc, o, err = e.at_terminal(['orch', 'relay', 'contacts', 'accept', S['signed_ph'], '--fingerprint', '''\(label)'''], cwd=str(e.ws('Pilatus')), env=e.env)
        assert rc == 0, (o + err)[-300:]
        e.orch('Pilatus', 'relay', 'inbox')
        ms = [json.load(open(x)) for x in glob.glob(str(e.ws('Pilatus')) + '/.orch/inbox/m_*.json')]
        m = [x for x in ms if 'Signed words from the phone \(run)' in json.dumps(x.get('body', {}))]
        out = json.dumps({'n': len(m), 'signed': (m[0].get('signed') or {}).get('origin') if m else None, 'env': bool(m and m[0].get('envelope'))})
        """)
        XCTAssertTrue(accepted.contains("\"n\": 1") && accepted.contains("\"signed\": \"person\"") && accepted.contains("\"env\": true"),
                      "after Accept the workspace handles the phone's signed words: \(accepted)")

        // ---- 4. a relay that changes messages on the way: its own copy (the phone shows only what was signed) and the
        //         signed bytes themselves (the phone refuses the message and says so)
        app.terminate()
        let changed = host("""
        import json, sqlite3, os, base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        e.orch('Reports', 'relay', 'send', S['signed_ph'], 'Original words from Reports \(run)')
        e.orch('Reports', 'relay', 'send', S['signed_ph'], 'Signed words that get broken \(run)')
        relay_stop(e)
        key = (e.tmp / 'relay-master.key').read_bytes()
        db = sqlite3.connect(str(e.rel.data / 'relay.db'))
        rows = db.execute("SELECT id, payload FROM messages WHERE from_addr=? AND type='text' ORDER BY seq DESC LIMIT 2", (ids['Reports'],)).fetchall()
        def edit(mid, blob, fn):
            plain = json.loads(AESGCM(key).decrypt(blob[:12], blob[12:], mid.encode()))
            assert plain['extra'].get('envelope'), 'a signed text'
            fn(plain)
            n = os.urandom(12)
            db.execute('UPDATE messages SET payload=? WHERE id=?', (n + AESGCM(key).encrypt(n, json.dumps(plain).encode(), mid.encode()), mid))
            return plain
        def outer(p):  # the relay's copy only
            p['body']['text'] = 'Changed words from the relay \(run)'
        def inner(p):  # the signed bytes
            env = p['extra']['envelope']
            raw = base64.urlsafe_b64decode(env['signed'] + '=' * (-len(env['signed']) % 4))
            assert b'get broken' in raw
            raw = raw.replace(b'get broken', b'got broken')
            env['signed'] = base64.urlsafe_b64encode(raw).rstrip(b'=').decode()
            p['body']['text'] = p['body']['text'].replace('get broken', 'got broken')
        (b_id, b_blob), (a_id, a_blob) = rows[0], rows[1]
        edit(a_id, bytes(a_blob), outer)
        edit(b_id, bytes(b_blob), inner)
        db.commit(); db.close()
        relay_start(e)
        e.orch('Reports', 'relay', 'send', S['signed_ph'], 'Words after the change \(run)')
        out = a_id + ' ' + b_id
        """)
        XCTAssertTrue(changed.hasPrefix("m_"), "changed two stored messages: \(changed)")
        app = launch(extra: ["-open", "general:\(rep)"])
        must(app, text(app, "Words after the change \(run)"), "the next message still shows", timeout: 40)
        XCTAssertTrue(text(app, "Original words from Reports \(run)").exists, "the relay's changed copy: the signed words show")
        XCTAssertFalse(text(app, "Changed words from the relay").exists, "the relay's words are never shown")
        XCTAssertFalse(text(app, "broken \(run)").exists, "changed signed bytes: the message is not shown")
        shot("4-general-after-change")
        app.navigationBars.buttons.element(boundBy: 0).tap()
        must(app, text(app, "changed on the way"), "the workspace names the message it did not show", timeout: 20)
        shot("5-changed-on-the-way")

        // ---- 5. a signed answer to a signed question
        let t = host("""
        import json, subprocess
        t = json.loads(e.orch('Pilatus', 'ticket', 'new', 'Signed answer check', '--json')[1])['id']
        S['sq'] = t
        p = subprocess.Popen(['orch', 'ask', t, 'Delete the old backups?', '--option', 'Yes', '--option', 'No', '--recommend', 'No', '--phone'],
                             cwd=str(e.ws('Pilatus')), env=e.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        S['sask'] = p
        e.pids.append(p.pid)
        out = t
        """)
        app.terminate()
        app = launch()
        let row = app.buttons["ticket-\(pil)|\(t)"]
        var n = 0
        while !row.waitForExistence(timeout: 5) && n < 8 { app.swipeUp(); n += 1 }
        must(app, row, "ticket row of the question", timeout: 20); row.tap()
        let yes = el(app, "answer-Yes")
        must(app, yes, "answer Yes", timeout: 30)
        shot("6-signed-question")
        yes.tap()
        let answered = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'answered-'")).firstMatch
        must(app, answered, "answered card", timeout: 40)
        shot("7-signed-answer")
        let applied = host("""
        import json, glob, time
        end = time.time() + 90   # `orch ask --phone` only sends: the workspace pulls and applies the answer
        q = {}
        while time.time() < end:
            e.orch('Pilatus', 'relay', 'inbox')
            q = json.loads(e.orch('Pilatus', 'ticket', 'show', S['sq'], '--json')[1])['questions'][0]
            if q.get('answer') is not None:
                break
            time.sleep(2)
        ms = [json.load(open(x)) for x in glob.glob(str(e.ws('Pilatus')) + '/.orch/inbox/m_*.json')]
        a = [m for m in ms if m.get('type') == 'answer' and m.get('from') == S['signed_ph']]
        sig = (a[-1].get('signed') or {}) if a else {}
        out = json.dumps({'answer': q.get('answer'), 'by': q.get('answered_by'), 'envelope': bool(a and a[-1].get('envelope')),
                          'qsha': len(sig.get('question_sha256') or ''), 'origin': sig.get('origin')})
        """)
        XCTAssertTrue(applied.contains("\"answer\": \"Yes\""), "the workspace applied the answer: \(applied)")
        XCTAssertTrue(applied.contains("\"envelope\": true") && applied.contains("\"qsha\": 64") && applied.contains("\"origin\": \"person\""),
                      "the answer came signed, naming the question: \(applied)")
        XCTAssertFalse(applied.contains("human:ph_"), "the workspace shows the phone's name, not its id: \(applied)")
        _ = ph
    }
}
