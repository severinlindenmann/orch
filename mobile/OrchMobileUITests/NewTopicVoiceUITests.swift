import XCTest

/// Voice-first New topic: talk, Done, the words appear, Send closes the sheet.
final class NewTopicVoiceUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    func testReviewStartsOnAndSwitchingItKeepsTypedText() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"]
        app.launch()
        XCTAssertTrue(app.buttons["new-chat"].waitForExistence(timeout: 15))
        app.buttons["new-chat"].tap()
        let compose = app.buttons["compose-new-topic"]
        if compose.waitForExistence(timeout: 5) { compose.tap() }
        let review = app.switches["nt-human-review"]
        XCTAssertTrue(review.waitForExistence(timeout: 10))
        XCTAssertEqual(review.value as? String, "1")
        review.tap()
        app.buttons["nt-type"].tap()
        XCTAssertEqual(review.value as? String, "0")
        let field = app.textFields["topic-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        field.tap(); field.typeText("Keep this request")
        review.tap()
        XCTAssertEqual(review.value as? String, "1")
        XCTAssertEqual(field.value as? String, "Keep this request")
    }

    func testTalkDoneTranscriptSend() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-fakeVoice", "YES"]
        app.launch()
        // "+" then New topic (current compose path; lane abd may open New topic straight from "+").
        XCTAssertTrue(app.buttons["new-chat"].waitForExistence(timeout: 15)); app.buttons["new-chat"].tap()
        let compose = app.buttons["compose-new-topic"]
        if compose.waitForExistence(timeout: 5) { compose.tap() }
        let mic = app.buttons["nt-mic"]
        XCTAssertTrue(mic.waitForExistence(timeout: 10)); mic.tap()
        let done = app.buttons["nt-done"]
        XCTAssertTrue(done.waitForExistence(timeout: 10))
        Thread.sleep(forTimeInterval: 2)
        done.tap()
        XCTAssertTrue(app.descendants(matching: .any)["nt-transcript"].firstMatch.waitForExistence(timeout: 15), "the words are shown")
        XCTAssertTrue(app.buttons["nt-record-more"].exists && app.buttons["nt-edit"].exists)
        app.buttons["nt-send"].tap()
        XCTAssertTrue(waitGone(mic, 15), "the New topic sheet closes after Send")
    }

    private func waitGone(_ el: XCUIElement, _ seconds: TimeInterval) -> Bool {
        let e = expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: el)
        return XCTWaiter().wait(for: [e], timeout: seconds) == .completed
    }
}
