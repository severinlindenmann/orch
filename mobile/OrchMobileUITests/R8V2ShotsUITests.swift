import XCTest

/// Evidence screenshots of the round-8 ticket chat, info, + sheet, offline wait, artifact viewer and pin sheet.
/// Runs only when the target folder exists.
final class R8V2ShotsUITests: XCTestCase {
    private var dir: URL!
    override func setUpWithError() throws {
        continueAfterFailure = false
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        dir = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/mobile-v3-messenger/build/shots/r8v2")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: dir.path), "no shots folder")
    }
    private func launch(_ extra: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-fakeVoice", "YES", "-undoSeconds", "60"] + extra
        app.launch()
        return app
    }
    private func shot(_ app: XCUIApplication, _ name: String) throws {
        sleep(2)
        try app.screenshot().pngRepresentation.write(to: dir.appendingPathComponent("\(name).png"))
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    func testTicketChatAndInfo() throws {
        var app = launch(["-openChat", "ws_pilatus001", "-openTicket", "t_7k3f9q"])
        XCTAssertTrue(el(app, "answer-TIMESTAMP").waitForExistence(timeout: 15))
        try shot(app, "ticket-questions")
        el(app, "composer-attach").tap()
        XCTAssertTrue(app.buttons["media-close"].waitForExistence(timeout: 10))
        try shot(app, "ask-sheet")
        app.terminate()
        app = launch(["-openChat", "ws_reports001", "-openTicket", "t_9k2m4q", "-openInfo", "YES"])
        XCTAssertTrue(el(app, "info-summary").waitForExistence(timeout: 15))
        try shot(app, "ticket-info")
        app.terminate()
    }

    func testOfflineWait() throws {
        let app = launch(["-mockFail", "YES", "-openChat", "ws_pilatus001"])
        let general = app.buttons["general-ws_pilatus001"]; if general.waitForExistence(timeout: 15) { general.tap() }
        let field = el(app, "composer-field"); XCTAssertTrue(field.waitForExistence(timeout: 15))
        field.tap(); field.typeText("Please remind me about the car tax."); el(app, "composer-send").tap()
        XCTAssertTrue(app.descendants(matching: .any)["receipt-queued"].waitForExistence(timeout: 10), "the clock marks the waiting message")
        XCTAssertFalse(app.staticTexts["Waiting · will send when online"].exists, "the offline banner says it; no caption per bubble")
        try shot(app, "offline-wait")
    }

    func testViewerAndPin() throws {
        let app = launch(["-m3Host", "viewer-html"])
        XCTAssertTrue(app.buttons["artifact-comment"].waitForExistence(timeout: 20))
        sleep(2)
        try shot(app, "artifact-page")
        app.buttons["artifact-comment"].tap()
        app.webViews.firstMatch.coordinate(withNormalizedOffset: CGVector(dx: 0.4, dy: 0.2)).tap()
        let text = app.textViews["pin-text"].firstMatch.exists ? app.textViews["pin-text"] : app.textFields["pin-text"]
        XCTAssertTrue(text.waitForExistence(timeout: 10))
        text.tap(); text.typeText("Make the menu button a little bigger.")
        try shot(app, "artifact-pin")
    }
}
