import XCTest

/// Evidence screenshots of round-8 settings, onboarding and Chat as a messenger. Runs only when the target folder exists.
final class R8V3ShotsUITests: XCTestCase {
    private var dir: URL!
    override func setUpWithError() throws {
        continueAfterFailure = false
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        dir = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/mobile-v3-messenger/build/shots/r8v3")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: dir.path), "no shots folder")
    }
    private func launch(_ extra: [String], paired: Bool = true) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock"] + (paired ? ["-seedPaired", "YES"] : []) + ["-undoSeconds", "60"] + extra
        app.launch()
        return app
    }
    private func shot(_ app: XCUIApplication, _ name: String) throws {
        sleep(2)
        try app.screenshot().pngRepresentation.write(to: dir.appendingPathComponent("\(name).png"))
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    func testOnboarding() throws {
        let app = launch([], paired: false)
        XCTAssertTrue(app.buttons.firstMatch.waitForExistence(timeout: 15))
        try shot(app, "welcome")
        app.buttons["invite-paste"].tap()
        if app.textFields["invite-field"].waitForExistence(timeout: 10) { try shot(app, "invite") }
    }

    func testSettings() throws {
        let app = launch(["-open", "settings"])
        XCTAssertTrue(el(app, "voice-settings").waitForExistence(timeout: 15))
        try shot(app, "settings")
        el(app, "voice-settings").tap()
        XCTAssertTrue(el(app, "voice-replies-menu").waitForExistence(timeout: 10))
        try shot(app, "voice-settings")
    }

    func testChat() throws {
        let app = launch(["-mockChatDays", "YES", "-open", "general:ws_pilatus001"])
        XCTAssertTrue(el(app, "composer-field").waitForExistence(timeout: 15))
        try shot(app, "chat-today")
        let h = el(app, "chat-history"); XCTAssertTrue(h.waitForExistence(timeout: 5)); h.tap()
        sleep(1)
        try shot(app, "chat-history")
    }
}
