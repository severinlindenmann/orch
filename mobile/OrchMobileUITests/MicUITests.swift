import XCTest

/// The mic is back in every chat composer: tap to record, tap to stop, the transcript lands in the field.
final class MicUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }
    private let said = "Send the weekly report on Friday."

    private func launch(_ extra: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-fakeVoice", "YES"] + extra
        app.launch()
        return app
    }

    private func speak(_ app: XCUIApplication, field: String) {
        let mic = app.buttons["mic"]
        XCTAssertTrue(mic.waitForExistence(timeout: 15))
        mic.tap()
        XCTAssertTrue(app.buttons["mic"].label.hasPrefix("Recording"))
        app.buttons["mic"].tap()
        let f = app.descendants(matching: .any)[field]
        var got = false
        for _ in 0..<40 where !got {
            got = ((f.value as? String) ?? "").contains(said)
            if !got { Thread.sleep(forTimeInterval: 0.25) }
        }
        XCTAssertTrue(got, "the transcript lands in the field")
    }

    func testNewChatMic() { speak(launch(["-openNewChat", "YES"]).self.afterPick(), field: "topic-field") }
}

private extension XCUIApplication {
    func afterPick() -> XCUIApplication {
        let pick = buttons["pick-ws_pilatus001"]
        _ = pick.waitForExistence(timeout: 15); pick.tap()
        buttons["pick-continue"].tap()
        return self
    }
}
