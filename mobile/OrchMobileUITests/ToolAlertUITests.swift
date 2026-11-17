import XCTest

/// Tool warning row on the workspace (contracts/tool-alert.md, mockup 5b) with the mock relay.
final class ToolAlertUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    /// Opens the Pilatus workspace the way tapping the warning's push does (`-openTextPush`).
    private func open(_ extra: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-openTextPush", "ws_pilatus001"] + extra
        app.launch()
        return app
    }

    private func shot(_ name: String) {
        let a = XCTAttachment(screenshot: XCUIScreen.main.screenshot()); a.name = name; a.lifetime = .keepAlways; add(a)
    }

    func testSoonWarningShowsOnWorkspace() {
        let app = open(["-mockToolAlert", "soon"])
        let row = app.descendants(matching: .any)["tool-alert-claude"].firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 10))
        XCTAssertTrue(row.label.contains("ends on Monday 23 November"))
        shot("tool-alert-soon")
    }

    func testStoppedWarningShowsOnWorkspace() {
        let app = open(["-mockToolAlert", "renew"])
        let row = app.descendants(matching: .any)["tool-alert-claude"].firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 10))
        XCTAssertTrue(row.label.contains("stopped working"))
        shot("tool-alert-renew")
    }

    func testNoWarningWithoutOne() {
        let app = open([])
        XCTAssertTrue(app.buttons["workspace-info"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.descendants(matching: .any)["tool-alert-claude"].exists)
        shot("tool-alert-none")
    }

    func testWorksAgainShowsNoRow() {
        let app = open(["-mockToolAlert", "works"])
        XCTAssertTrue(app.buttons["workspace-info"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.descendants(matching: .any)["tool-alert-claude"].exists)
    }
}
