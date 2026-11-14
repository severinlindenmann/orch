import XCTest

/// The shared composer (hold-to-record; recording itself is covered in ConversationUITests) is in the New topic screen.
final class MicUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }
    
    private func launch(_ extra: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-fakeVoice", "YES"] + extra
        app.launch()
        return app
    }

    func testNewChatMic() {
        let app = launch(["-openNewChat", "YES"])
        XCTAssertTrue(app.buttons["nt-type"].waitForExistence(timeout: 15)); app.buttons["nt-type"].tap()   // "Type instead"
        let mic = app.descendants(matching: .any)["composer-mic"].firstMatch
        XCTAssertTrue(mic.waitForExistence(timeout: 15), "the shared composer has the mic")
        XCTAssertTrue(app.descendants(matching: .any)["topic-field"].firstMatch.exists)
    }
}
