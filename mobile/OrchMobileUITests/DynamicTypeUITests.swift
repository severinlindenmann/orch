import XCTest

/// Regression: fonts must follow Dynamic Type (the tab bar and buttons once used fixed sizes), on the paired Chats screen
/// and on both fingerprints a person compares (Accept card and Settings, ORCH-2128).
@MainActor final class DynamicTypeUITests: XCTestCase {
    private static let largest = "UICTContentSizeCategoryAccessibilityXXXL"
    /// The whole value: eight groups of four characters (MessageSignature.fingerprint).
    private static let fullValue = try! NSRegularExpression(pattern: "([0-9A-Z]{4} ){7}[0-9A-Z]{4}")

    private func launch(_ extra: [String], size: String? = nil) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"] + extra
        if let size { app.launchArguments += ["-UIPreferredContentSizeCategoryName", size] }
        app.launch()
        return app
    }

    func testHomeFontsSupportDynamicType() throws {
        let app = launch([])
        XCTAssertTrue(app.buttons["room-ws_pilatus001"].waitForExistence(timeout: 15))
        sleep(2)
        try app.performAccessibilityAudit(for: .dynamicType)
    }

    private func acceptFingerprint(_ size: String?) -> (XCUIApplication, XCUIElement) {
        let app = launch(["-openChat", "ws_pilatus001", "-mockSigningKey", "YES"], size: size)
        let value = app.descendants(matching: .any)["accept-fingerprint"].firstMatch
        XCTAssertTrue(value.waitForExistence(timeout: 15))
        return (app, value)
    }

    private func phoneFingerprint(_ size: String?) -> (XCUIApplication, XCUIElement) {
        let app = launch(["-startTab", "settings"], size: size)
        let value = app.descendants(matching: .any)["phone-fingerprint"].firstMatch
        XCTAssertTrue(value.waitForExistence(timeout: 15))
        for _ in 0..<15 where !value.isHittable { app.swipeUp() }
        XCTAssertTrue(value.isHittable)
        return (app, value)
    }

    private func assertGrowsInFull(_ open: (String?) -> (XCUIApplication, XCUIElement), id: String) throws {
        var (app, value) = open(nil)
        let small = value.frame.height
        // Only this value is judged: other parts of the screen have their own checks.
        try app.performAccessibilityAudit(for: .dynamicType) { $0.element?.identifier != id }
        app.terminate()

        (app, value) = open(Self.largest)
        let label = value.label
        XCTAssertNotNil(Self.fullValue.firstMatch(in: label, range: NSRange(label.startIndex..., in: label)),
                        "VoiceOver reads the whole fingerprint: \(label)")
        XCTAssertGreaterThan(value.frame.height, small * 1.5, "the fingerprint grows with the text size")
        XCTAssertLessThanOrEqual(value.frame.maxX, app.windows.firstMatch.frame.maxX + 0.5, "it wraps inside the screen")
        try app.performAccessibilityAudit(for: [.dynamicType, .textClipped]) { $0.element?.identifier != id }
        app.terminate()
    }

    func testAcceptFingerprintFollowsTextSize() throws {
        try assertGrowsInFull(acceptFingerprint, id: "accept-fingerprint")
    }

    func testPhoneFingerprintFollowsTextSize() throws {
        try assertGrowsInFull(phoneFingerprint, id: "phone-fingerprint")
    }
}
