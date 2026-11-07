import XCTest

/// DEBUG launch arg `-open general:<ws> | topic:<ws>:<ticket> | workspace:<ws> | settings:chats | archived` (MockRelay).
final class OpenArgUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }
    private func launch(_ open: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-open", open]
        app.launch()
        return app
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    func testOpenGeneralTopicWorkspaceAndSettings() {
        var app = launch("general:ws_pilatus001")
        XCTAssertTrue(el(app, "composer").waitForExistence(timeout: 20), "general conversation")
        app.terminate()
        app = launch("topic:ws_pilatus001:t_q3sum1")
        XCTAssertTrue(el(app, "composer").waitForExistence(timeout: 20), "topic conversation")
        XCTAssertTrue(el(app, "chat-title").exists)
        app.terminate()
        app = launch("workspace:ws_pilatus001")
        XCTAssertTrue(app.buttons["general-ws_pilatus001"].waitForExistence(timeout: 20), "workspace screen")
        app.terminate()
        app = launch("settings:chats")
        XCTAssertTrue(el(app, "voice-settings").waitForExistence(timeout: 20), "settings")
        app.terminate()
        app = launch("archived")   // ignored until the archive exists: lands on Chats
        XCTAssertTrue(el(app, "new-chat").waitForExistence(timeout: 20), "unknown target is ignored")
    }
}
