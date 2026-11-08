import XCTest

final class OwnerTF1SettingsUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    func testVoiceRowBlankSpaceOpensVoiceSettings() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"]
        app.launch()

        let settings = app.buttons["settings-button"]
        XCTAssertTrue(settings.waitForExistence(timeout: 15))
        settings.tap()

        let voice = app.buttons["voice-settings"]
        XCTAssertTrue(voice.waitForExistence(timeout: 10))
        for _ in 0..<6 {
            if voice.isHittable { break }
            app.swipeUp()
        }
        XCTAssertTrue(voice.isHittable)
        // Tap the spacer between the title and chevron, where the owner saw no response.
        voice.coordinate(withNormalizedOffset: CGVector(dx: 0.6, dy: 0.5)).tap()

        XCTAssertTrue(app.navigationBars["Voice"].waitForExistence(timeout: 5))
        for mode in ["auto", "always", "never"] {
            XCTAssertTrue(app.buttons["speak-\(mode)"].exists)
        }
        XCTAssertTrue(app.switches["I speak Swiss German"].exists)
        let limit = app.buttons.containing(.staticText, identifier: "Monthly limit for voice replies").firstMatch
        for _ in 0..<4 {
            if limit.isHittable { break }
            app.swipeUp()
        }
        XCTAssertTrue(limit.isHittable)
        limit.tap()
        XCTAssertTrue(app.buttons["$10"].waitForExistence(timeout: 5))
    }
}
