import XCTest

/// Real-relay check in the Simulator (not in CI): runs only with `TEST_RUNNER_ORCH_REAL=1` plus the values below, one test
/// per xcodebuild call, with workspace steps on the host in between (pair link, workspace id, ticket id, shots folder).
final class RealRelayUITests: XCTestCase {
    private let env = ProcessInfo.processInfo.environment
    override func setUpWithError() throws {
        continueAfterFailure = false
        try XCTSkipUnless(env["ORCH_REAL"] == "1", "real relay check: set TEST_RUNNER_ORCH_REAL=1")
    }

    private func shot(_ name: String) {
        guard let dir = env["ORCH_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(name).png"))
    }

    private func launch(reset: Bool = false) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-undoSeconds", "4"] + (reset ? ["-resetState", "YES"] : [])
        app.launch()
        return app
    }

    private func any(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id] }
    private func field(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.textViews[id].exists ? app.textViews[id] : app.textFields[id]
    }

    /// Pair with the invitation link, see the workspace chat, start a new chat with a text.
    func test1PairAndNewChat() {
        let app = launch(reset: true)
        XCTAssertTrue(app.buttons["Paste invitation link"].waitForExistence(timeout: 15))
        app.buttons["Paste invitation link"].tap()
        let f = app.textFields["invite-field"]
        XCTAssertTrue(f.waitForExistence(timeout: 5))
        f.tap(); f.typeText(env["ORCH_PAIR_LINK"] ?? "")
        app.buttons["invite-continue"].tap()
        XCTAssertTrue(app.buttons["Connect this phone"].waitForExistence(timeout: 5))
        shot("02-invite-found")
        app.buttons["Connect this phone"].tap()
        XCTAssertTrue(app.buttons["Not now"].waitForExistence(timeout: 20))
        app.buttons["Not now"].tap()
        let ws = env["ORCH_WS"] ?? ""
        XCTAssertTrue(app.buttons["room-\(ws)"].waitForExistence(timeout: 20))
        shot("03-chats")
        app.buttons["new-chat"].tap()
        if app.buttons["pick-\(ws)"].waitForExistence(timeout: 3) {
            app.buttons["pick-\(ws)"].tap(); app.buttons["pick-continue"].tap()
        }
        let topic = field(app, "topic-field")
        XCTAssertTrue(topic.waitForExistence(timeout: 5))
        topic.tap(); topic.typeText("Make the Q3 chart")
        shot("04-new-chat")
        app.buttons["topic-start"].tap()
        XCTAssertTrue(app.staticTexts["composer-note"].waitForExistence(timeout: 15), "landed in the ticket chat")
        sleep(3)
        shot("05-new-ticket-chat")
    }

    /// After the workspace made the ticket, added tasks + an image and asked: list, key search, ticket chat, answer + undo.
    func test2TicketChatAndAnswer() {
        let app = launch()
        let ws = env["ORCH_WS"] ?? "", tid = env["ORCH_TICKET"] ?? "", key = env["ORCH_KEY"] ?? ""
        let row = app.buttons["ticket-\(ws)|\(tid)"]
        XCTAssertTrue(row.waitForExistence(timeout: 20), "ticket row in Chats")
        shot("06-chats-with-ticket")
        if !key.isEmpty {
            XCTAssertTrue(row.label.contains(key), "row shows the key: \(row.label)")
            let search = app.textFields["chat-search"]
            search.tap(); search.typeText(key)
            XCTAssertTrue(row.waitForExistence(timeout: 5))
            shot("07-search-key")
            if app.buttons["Cancel"].exists { app.buttons["Cancel"].tap() }
        }
        row.tap()
        XCTAssertTrue(app.staticTexts["composer-note"].waitForExistence(timeout: 10))
        XCTAssertTrue(any(app, "tasks-card").waitForExistence(timeout: 10), "tasks card")
        XCTAssertTrue(any(app, "attachment-image").waitForExistence(timeout: 10), "image attachment")
        shot("08-ticket-chat")
        let yes = app.buttons["answer-yes"]
        var tries = 0
        while !yes.exists && tries < 4 { app.swipeUp(); tries += 1 }
        XCTAssertTrue(yes.waitForExistence(timeout: 15), "question with options")
        shot("09-question")
        yes.tap()
        let undo = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'undo-'")).firstMatch
        XCTAssertTrue(undo.waitForExistence(timeout: 3))
        shot("10-undo")
        undo.tap()
        XCTAssertTrue(app.buttons["answer-yes"].waitForExistence(timeout: 3))
        app.buttons["answer-yes"].tap()
        let answered = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'answered-'")).firstMatch
        XCTAssertTrue(answered.waitForExistence(timeout: 15))
        shot("11-answered")
    }

    /// Look only: the ticket chat after more results, then its info screen (history with role).
    func test5LookTicketAndInfo() {
        let app = launch()
        let ws = env["ORCH_WS"] ?? "", tid = env["ORCH_TICKET"] ?? ""
        let row = app.buttons["ticket-\(ws)|\(tid)"]
        XCTAssertTrue(row.waitForExistence(timeout: 20))
        row.tap()
        XCTAssertTrue(app.staticTexts["composer-note"].waitForExistence(timeout: 10))
        sleep(4)
        shot("14-ticket-images")
        app.buttons.matching(NSPredicate(format: "label CONTAINS[c] 'info' OR label CONTAINS[c] 'details'")).firstMatch.tap()
        sleep(2)
        shot("15-info")
        if app.buttons["History"].exists { app.buttons["History"].tap(); sleep(1); shot("16-info-history") }
    }

    /// Relay goes down while the chat is open: the text waits on the phone.
    func test3OfflineQueues() {
        let app = launch()
        let ws = env["ORCH_WS"] ?? "", tid = env["ORCH_TICKET"] ?? ""
        let row = app.buttons["ticket-\(ws)|\(tid)"]
        XCTAssertTrue(row.waitForExistence(timeout: 20))
        row.tap()
        let f = field(app, "composer-field")
        XCTAssertTrue(f.waitForExistence(timeout: 10))
        // the host stops the relay once the chat is open (handshake files in ORCH_SIGNAL)
        let sig = URL(fileURLWithPath: env["ORCH_SIGNAL"] ?? NSTemporaryDirectory())
        try? Data().write(to: sig.appendingPathComponent("opened"))
        var waited = 0
        while !FileManager.default.fileExists(atPath: sig.appendingPathComponent("down").path) && waited < 60 { sleep(1); waited += 1 }
        f.tap(); f.typeText("Sent while offline")
        app.buttons["composer-send"].tap()
        XCTAssertTrue(app.staticTexts["Waiting to send"].waitForExistence(timeout: 15))
        shot("12-offline-waiting")
    }

    /// Relay back: the waiting text goes out by itself.
    func test4OutboxFlushes() {
        let app = launch()
        let ws = env["ORCH_WS"] ?? "", tid = env["ORCH_TICKET"] ?? ""
        let row = app.buttons["ticket-\(ws)|\(tid)"]
        XCTAssertTrue(row.waitForExistence(timeout: 20))
        row.tap()
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS 'Sent while offline'")).firstMatch.waitForExistence(timeout: 10))
        var waited = 0
        while app.staticTexts["Waiting to send"].exists && waited < 40 { sleep(1); waited += 1 }
        XCTAssertFalse(app.staticTexts["Waiting to send"].exists, "the waiting text did not go out")
        shot("13-offline-sent")
    }

    /// Tickets made on the host (never texted from the phone) show nested under the workspace; each opens its ticket chat.
    func test6ThreeTicketsNested() {
        let app = launch(reset: true)
        XCTAssertTrue(app.buttons["Paste invitation link"].waitForExistence(timeout: 15))
        app.buttons["Paste invitation link"].tap()
        let f = app.textFields["invite-field"]
        XCTAssertTrue(f.waitForExistence(timeout: 5))
        f.tap(); f.typeText(env["ORCH_PAIR_LINK"] ?? "")
        app.buttons["invite-continue"].tap()
        app.buttons["Connect this phone"].tap()
        XCTAssertTrue(app.buttons["Not now"].waitForExistence(timeout: 20)); app.buttons["Not now"].tap()
        let ws = env["ORCH_WS"] ?? ""
        XCTAssertTrue(app.buttons["room-\(ws)"].waitForExistence(timeout: 20))
        // the host refreshes its phone list and syncs its open tickets once this phone is paired (handshake files)
        let sig = URL(fileURLWithPath: env["ORCH_SIGNAL"] ?? NSTemporaryDirectory())
        try? Data().write(to: sig.appendingPathComponent("paired"))
        var waited = 0
        while !FileManager.default.fileExists(atPath: sig.appendingPathComponent("synced").path) && waited < 120 { sleep(1); waited += 1 }
        app.terminate(); app.launchArguments = ["-undoSeconds", "4"]; app.launch()   // the app reads the feed again when it opens
        let ids = (env["ORCH_TICKETS"] ?? "").split(separator: ",").map(String.init)
        XCTAssertEqual(ids.count, 3)
        _ = app.buttons["ticket-\(ws)|\(ids[0])"].waitForExistence(timeout: 25); shot("19-chats-after-pair")
        for id in ids { XCTAssertTrue(app.buttons["ticket-\(ws)|\(id)"].waitForExistence(timeout: 25), "ticket \(id) nested") }
        shot("20-chats-three-tickets")
        for (n, id) in ids.enumerated() {
            app.buttons["ticket-\(ws)|\(id)"].tap()
            XCTAssertTrue(app.staticTexts["composer-note"].waitForExistence(timeout: 10))
            XCTAssertTrue(app.buttons["mic"].exists, "mic in the ticket chat")
            sleep(1); shot("2\(n + 1)-ticket-chat-\(n + 1)")
            app.navigationBars.buttons.element(boundBy: 0).tap()
            XCTAssertTrue(app.buttons["ticket-\(ws)|\(id)"].waitForExistence(timeout: 10))
        }
    }
}
