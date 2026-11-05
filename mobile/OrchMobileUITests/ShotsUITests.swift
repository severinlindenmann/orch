import XCTest

/// Evidence screenshots for the PR (default size and Dynamic Type XXL). Runs only when the target folder exists
/// (`ORCH_SHOTS_DIR` is not needed: the folder under the host home is the switch), so CI skips it.
final class ShotsUITests: XCTestCase {
    private var dir: URL!
    override func setUpWithError() throws {
        continueAfterFailure = false
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        dir = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/v2-plan-2026-11-05/build/shots/mobile")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: dir.path), "no shots folder")
    }

    private func launch(_ extra: [String], xxl: Bool) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"] + extra
        if xxl { app.launchArguments += ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryXXL"] }
        app.launch()
        return app
    }
    private func shot(_ app: XCUIApplication, _ name: String, xxl: Bool) throws {
        sleep(1)
        try app.screenshot().pngRepresentation.write(to: dir.appendingPathComponent("\(name)-\(xxl ? "xxl" : "default").png"))
    }

    func testShotsDefault() throws { try run(xxl: false) }
    func testShotsXXL() throws { try run(xxl: true) }

    private func run(xxl: Bool) throws {
        // 1 + 2: Your tickets (all three groups), ticket detail sheet
        var app = launch([], xxl: xxl)
        XCTAssertTrue(app.staticTexts["Invoice CSV export"].waitForExistence(timeout: 15))
        try shot(app, "1-your-tickets", xxl: xxl)
        app.buttons["ticket-ws_reports001|t_9k2m4q"].tap()
        XCTAssertTrue(app.staticTexts["ticket-title"].waitForExistence(timeout: 5) || app.otherElements["ticket-title"].exists || app.descendants(matching: .any)["ticket-title"].waitForExistence(timeout: 5))
        try shot(app, "2-ticket-detail", xxl: xxl)
        app.terminate()

        // 3: Ask + Got it
        app = launch(["-startTab", "send"], xxl: xxl)
        let field = app.textViews["transcript"]
        XCTAssertTrue(field.waitForExistence(timeout: 15))
        field.tap(); field.typeText("Prepare the Q3 summary")
        app.buttons["keyboard-done"].tap()
        let send = app.buttons["send-button"]
        if !send.isHittable { app.swipeUp() }
        send.tap()
        XCTAssertTrue(app.staticTexts["ack-line"].waitForExistence(timeout: 10))
        try shot(app, "3-ask-got-it", xxl: xxl)
        app.terminate()

        // 4: allow question
        app = launch(["-startTab", "questions", "-mockAllow", "YES", "-openQuestion", "m_q3allow00000003"], xxl: xxl)
        XCTAssertTrue(app.buttons["answer-Once"].waitForExistence(timeout: 15))
        try shot(app, "4-allow-question", xxl: xxl)
        app.terminate()

        // 5: normal question, 5 s undo window
        app = launch(["-startTab", "questions"], xxl: xxl)
        XCTAssertTrue(app.buttons["answer-TIMESTAMP"].waitForExistence(timeout: 15))
        app.buttons["answer-TIMESTAMP"].tap()
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'undo-'")).firstMatch.waitForExistence(timeout: 5))
        try shot(app, "5-question-undo", xxl: xxl)
        app.terminate()

        // 6: answered by someone else first (409)
        app = launch(["-startTab", "questions", "-mockRace", "YES", "-undoSeconds", "1"], xxl: xxl)
        XCTAssertTrue(app.buttons["answer-TIMESTAMP"].waitForExistence(timeout: 15))
        app.buttons["answer-TIMESTAMP"].tap()
        XCTAssertTrue(app.staticTexts["Already answered"].waitForExistence(timeout: 15))
        try shot(app, "6-answered-by-other", xxl: xxl)
        app.terminate()
    }
}
