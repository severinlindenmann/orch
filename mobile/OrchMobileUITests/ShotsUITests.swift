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

        // The DATE/TIMESTAMP question belongs to topic PIL-13, not General.
        app = launch(["-openChat", "ws_pilatus001", "-openTicket", "t_7k3f9q"])
        let timestamp = app.descendants(matching: .any)["answer-TIMESTAMP"].firstMatch
        XCTAssertTrue(timestamp.waitForExistence(timeout: 20))
        try shot(app, "3-topic-question")
        timestamp.tap()
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'undo-'")).firstMatch.waitForExistence(timeout: 5))
        try shot(app, "4-question-undo")
        app.terminate()
    }

    /// Ticket links as link cards (tile, type, add-on status): shots for the links build, when its folder exists.
    func testLinkCardShots() throws {
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        let out = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/v2-plan-2026-11-05/build/shots/links-build")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: out.path), "no shots folder")
        dir = out
        let app = launch(["-openChat", "ws_reports001", "-openTicket", "t_9k2m4q", "-openInfo", "YES"])
        defer { app.terminate() }
        let links = app.buttons["info-tab-links"]
        XCTAssertTrue(links.waitForExistence(timeout: 20))
        links.tap()
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'info-item-'")).firstMatch.waitForExistence(timeout: 15))
        try shot(app, "10-phone-info-links")
    }
}
