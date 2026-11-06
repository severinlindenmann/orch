import XCTest

/// Evidence screenshots of the chat screens for the PR. Runs only when the target folder exists
/// (the folder under the host home is the switch), so CI skips it.
final class ShotsUITests: XCTestCase {
    private var dir: URL!
    override func setUpWithError() throws {
        continueAfterFailure = false
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        dir = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/v2-plan-2026-11-05/build/shots/mobile-chat")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: dir.path), "no shots folder")
    }

    private func launch(_ extra: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-undoSeconds", "30"] + extra
        app.launch()
        return app
    }
    private func shot(_ app: XCUIApplication, _ name: String) throws {
        sleep(2)
        try app.screenshot().pngRepresentation.write(to: dir.appendingPathComponent("\(name).png"))
    }

    func testShots() throws {
        var app = launch([])
        XCTAssertTrue(app.buttons["room-ws_pilatus001"].waitForExistence(timeout: 15))
        try shot(app, "1-chats"); app.terminate()

        app = launch([])
        let search = app.textFields["chat-search"]; XCTAssertTrue(search.waitForExistence(timeout: 15))
        search.tap(); search.typeText("board"); try shot(app, "2-search"); app.terminate()

        app = launch(["-openChat", "ws_pilatus001"])
        XCTAssertTrue(app.buttons["answer-TIMESTAMP"].waitForExistence(timeout: 15))
        try shot(app, "3-workspace-chat")
        app.buttons["answer-TIMESTAMP"].tap()
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'undo-'")).firstMatch.waitForExistence(timeout: 5))
        try shot(app, "4-question-undo"); app.terminate()

        app = launch(["-mockAllow", "YES", "-openChat", "ws_pilatus001"])
        XCTAssertTrue(app.buttons["answer-Once"].waitForExistence(timeout: 15))
        try shot(app, "5-allow"); app.terminate()

        app = launch(["-openChat", "ws_reports001", "-openTicket", "t_9k2m4q"])
        XCTAssertTrue(app.descendants(matching: .any)["tasks-card"].waitForExistence(timeout: 15))
        try shot(app, "6-ticket-chat-running")
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Tasks'")).firstMatch.tap(); try shot(app, "7-ticket-tasks-open"); app.terminate()

        app = launch(["-openChat", "ws_pilatus001", "-openTicket", "t_q3sum1"])
        XCTAssertTrue(app.descendants(matching: .any)["tasks-card"].waitForExistence(timeout: 15))
        try shot(app, "8-ticket-chat-done"); app.terminate()

        app = launch(["-openChat", "ws_pilatus001", "-openTicket", "t_q3sum1", "-openInfo", "YES"])
        XCTAssertTrue(app.descendants(matching: .any)["info-tabs"].waitForExistence(timeout: 15))
        try shot(app, "9-chat-info-media")
        app.buttons["Links 1"].tap(); try shot(app, "10-chat-info-links"); app.terminate()

        app = launch(["-openNewChat", "YES"])
        XCTAssertTrue(app.buttons["pick-ws_pilatus001"].waitForExistence(timeout: 15))
        try shot(app, "11-new-chat"); app.terminate()

        app = launch(["-mockEmpty", "YES"])
        XCTAssertTrue(app.descendants(matching: .any)["chats-empty"].waitForExistence(timeout: 15))
        try shot(app, "12-empty"); app.terminate()

        app = launch(["-mockFail", "YES", "-openChat", "ws_pilatus001"])
        XCTAssertTrue(app.descendants(matching: .any)["offline-banner"].waitForExistence(timeout: 15))
        try shot(app, "13-offline"); app.terminate()

        app = launch(["-openQuestion", "m_q1date0ts0000001"])
        XCTAssertTrue(app.descendants(matching: .any)["question-m_q1date0ts0000001"].waitForExistence(timeout: 15))
        try shot(app, "14-push-opened")
    }
}
