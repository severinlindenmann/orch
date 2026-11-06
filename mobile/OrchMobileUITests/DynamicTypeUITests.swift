import XCTest

/// Regression: fonts must follow Dynamic Type (the tab bar and buttons once used fixed sizes), on the paired Chats screen.
@MainActor final class DynamicTypeUITests: XCTestCase {
    func testHomeFontsSupportDynamicType() throws {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"]
        app.launch()
        XCTAssertTrue(app.buttons["room-ws_pilatus001"].waitForExistence(timeout: 15))
        sleep(2)
        // The tab bar is deliberately capped at xxxLarge (like system tab bars); everything else must scale.
        let tabBar: Set<String> = ["Chats", "Settings"]
        try app.performAccessibilityAudit(for: .dynamicType) { issue in tabBar.contains(issue.element?.label ?? "") }
    }
}
