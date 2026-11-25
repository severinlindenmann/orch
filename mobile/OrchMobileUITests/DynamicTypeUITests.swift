import XCTest

/// Regression: fonts must follow Dynamic Type (the tab bar and buttons once used fixed sizes), on the paired Chats screen.
@MainActor final class DynamicTypeUITests: XCTestCase {
    func testHomeFontsSupportDynamicType() throws {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"]
        app.launch()
        XCTAssertTrue(app.buttons["room-ws_pilatus001"].waitForExistence(timeout: 15))
        sleep(2)
        try app.performAccessibilityAudit(for: .dynamicType)
    }

    /// Largest accessibility size: the chat list keeps its labelled buttons and passes the Dynamic Type audit.
    func testChatsAtLargestSizeKeepLabelsAndFit() throws {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES",
                                "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        app.launch()
        XCTAssertTrue(app.buttons["room-ws_pilatus001"].waitForExistence(timeout: 15))
        XCTAssertEqual(app.buttons["settings-button"].label, "Settings")
        XCTAssertEqual(app.buttons["new-chat"].label, "New chat")
        try app.performAccessibilityAudit(for: [.dynamicType, .sufficientElementDescription])
    }
}
