import XCTest

/// ORCH-742 (look B): a saved ticket says Prepared / Preparing under the title; the What I found row opens the sources.
/// Pictures for the PR land in ~/orch-dev/state/orch742-shots when that folder exists.
final class PrepareUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    private func launch(_ ticket: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-mockPrepare", "YES",
                                "-openChat", "ws_pilatus001", "-openTicket", ticket]
        app.launch()
        return app
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }
    private func shot(_ app: XCUIApplication, _ name: String) {
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        let dir = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/orch742-shots")
        guard FileManager.default.fileExists(atPath: dir.path) else { return }
        sleep(1)
        try? app.screenshot().pngRepresentation.write(to: dir.appendingPathComponent(name + ".png"))
    }

    func testPreparedTicketShowsTheMarkAndWhatIFound() {
        let app = launch("t_prepspring")
        XCTAssertTrue(el(app, "chat-prepare").waitForExistence(timeout: 15))
        let row = el(app, "found-toggle")
        XCTAssertTrue(row.exists)
        shot(app, "phone-prepared")
        row.tap()
        XCTAssertTrue(el(app, "found-close").waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Could not open"].exists)
        XCTAssertTrue(app.staticTexts["Email from Anna, yesterday"].exists)
        shot(app, "phone-found")
        el(app, "found-close").tap()
    }

    func testPreparingTicketSaysPreparingWithoutAFoundRow() {
        let app = launch("t_prepsurvey")
        XCTAssertTrue(el(app, "chat-prepare").waitForExistence(timeout: 15))
        XCTAssertFalse(el(app, "found-toggle").exists)
        shot(app, "phone-preparing")
    }
}
