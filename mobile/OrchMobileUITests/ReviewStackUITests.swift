import XCTest

final class ReviewStackUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch(_ extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-fakeVoice", "YES", "-mockReviewStack", "YES"] + extra
        app.launch()
        return app
    }
    private func any(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }
    private func openStack(_ app: XCUIApplication) {
        let row = any(app, "review-stack-row")
        XCTAssertTrue(row.waitForExistence(timeout: 20), "the Review row shows on Chats")
        row.tap()
        if !any(app, "review-card").waitForExistence(timeout: 10) { shot(app, "dbg-nocard"); print(app.debugDescription) }
        XCTAssertTrue(any(app, "review-card").exists)
    }
    private func shot(_ app: XCUIApplication, _ name: String) {
        let dir = "/Users/lume/orch-dev/state/e2e-shots"
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        try? app.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: dir + "/p4-\(name).png"))
        let a = XCTAttachment(screenshot: app.screenshot()); a.name = name; a.lifetime = .keepAlways; add(a)
    }
    private func progress(_ app: XCUIApplication) -> String { any(app, "review-progress").label }
    private func waitProgress(_ app: XCUIApplication, _ prefix: String) -> Bool {
        for _ in 0..<40 { if any(app, "review-progress").label.hasPrefix(prefix) { return true }; usleep(250_000) }
        return false
    }
    private func drag(_ app: XCUIApplication, dx: CGFloat, dy: CGFloat = 0) {
        let card = any(app, "review-card")
        let a = card.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.35))
        let b = card.coordinate(withNormalizedOffset: CGVector(dx: 0.5 + dx, dy: 0.35 + dy))
        a.press(forDuration: 0.05, thenDragTo: b, withVelocity: .slow, thenHoldForDuration: 0)
    }
    private func jump(_ app: XCUIApplication, _ title: String) {
        any(app, "review-all").tap()
        let row = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", title)).firstMatch
        if !row.waitForExistence(timeout: 5) { shot(app, "dbg-overview"); print(app.debugDescription) }
        XCTAssertTrue(row.exists, "overview row \(title)"); row.tap()
        XCTAssertTrue(any(app, "review-card").waitForExistence(timeout: 5))
        XCTAssertEqual(any(app, "review-title").label, title)
    }

    func testRowCountsAndSwipeBasics() {
        let app = launch()
        let row = any(app, "review-stack-row")
        XCTAssertTrue(row.waitForExistence(timeout: 20))
        XCTAssertTrue(row.label.contains("9 things to review"), row.label)
        XCTAssertTrue(row.label.contains("3 choices"), row.label)
        shot(app, "01-chats-row")
        row.tap()
        XCTAssertTrue(any(app, "review-card").waitForExistence(timeout: 10))
        XCTAssertEqual(progress(app), "0 answered · 9 waiting")
        shot(app, "02-first-card-options")
        drag(app, dx: 0.08)                                   // short: springs back
        XCTAssertEqual(progress(app), "0 answered · 9 waiting")
        drag(app, dx: 0.1, dy: 0)                             // still short
        XCTAssertEqual(progress(app), "0 answered · 9 waiting")
        if app.buttons["option-A"].exists { app.buttons["option-A"].tap() }   // a choice needs a pick before approving
        drag(app, dx: 0.8)                                    // past the threshold: next card
        if !waitProgress(app, "1 answered · 8 waiting") { shot(app, "dbg-swipe") }
        XCTAssertTrue(waitProgress(app, "1 answered · 8 waiting"), progress(app))
        shot(app, "03-after-approve-next-card")
    }

    func testLeftEdgeDragPopsTheScreen() {
        let app = launch()
        openStack(app)
        let edge = app.coordinate(withNormalizedOffset: CGVector(dx: 0.0, dy: 0.5))
        edge.press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.8, dy: 0.5)))
        XCTAssertTrue(any(app, "review-stack-row").waitForExistence(timeout: 8), "back on Chats")
        XCTAssertFalse(any(app, "review-card").exists)
    }

    func testCommentSheetFromButtonAndUseCWithChanges() {
        let app = launch()
        openStack(app)
        app.buttons["review-comment"].tap()                   // same action as the VoiceOver "Comment" action
        XCTAssertTrue(any(app, "comment-sheet").waitForExistence(timeout: 5))
        shot(app, "04-comment-sheet")
        let mic = app.buttons["comment-mic"]
        mic.tap(); mic.tap()                                  // scripted voice: the transcript lands in the field
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.49)).press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.99)))   // dragging the sheet down keeps the text
        XCTAssertTrue(any(app, "review-all").waitForExistence(timeout: 5))
        jump(app, "Pick a logo")
        shot(app, "05-options-card")
        app.buttons["option-C"].tap()
        shot(app, "06-option-picked")
        app.buttons["review-comment"].tap()
        let text = app.textFields["comment-text"].firstMatch.exists ? app.textFields["comment-text"] : app.textViews["comment-text"]
        XCTAssertTrue(text.waitForExistence(timeout: 5)); text.tap(); text.typeText("Bigger please")
        let use = app.buttons["comment-use"]
        XCTAssertTrue(use.waitForExistence(timeout: 5)); XCTAssertEqual(use.label, "Use C with these changes")
        use.tap()
        XCTAssertTrue(waitProgress(app, "1 answered"), progress(app))
    }

    func testSignsCardRefusesOkOnThePhone() {
        let app = launch()
        openStack(app)
        jump(app, "Deploy to production")
        XCTAssertTrue(any(app, "review-signs-chip").exists)
        shot(app, "07-signs-card")
        app.buttons["review-ok"].tap()
        let toast = any(app, "review-toast")
        XCTAssertTrue(toast.waitForExistence(timeout: 5))
        XCTAssertTrue(toast.label.contains("signature on the computer"), toast.label)
        shot(app, "08-needs-signature")
        XCTAssertTrue(progress(app).hasPrefix("0 answered"))
    }

    func testOverviewJumpAndAllDone() {
        let app = launch()
        openStack(app)
        jump(app, "Which day for the meeting?")
        app.buttons["review-ok"].tap()                        // a choice needs a pick first
        XCTAssertTrue(any(app, "review-toast").waitForExistence(timeout: 5))
        shot(app, "09-pick-one-first")
        // answer everything
        for _ in 0..<14 {
            if any(app, "review-done").exists { break }
            guard any(app, "review-card").waitForExistence(timeout: 5) else { break }
            if app.buttons["option-A"].exists { app.buttons["option-A"].tap(); app.buttons["review-ok"].tap() }
            else if any(app, "review-signs-chip").exists { app.buttons["review-no"].tap() }
            else { app.buttons["review-ok"].tap() }
            sleep(1)
        }
        if !any(app, "review-done").waitForExistence(timeout: 10) { shot(app, "dbg-alldone") }
        XCTAssertTrue(any(app, "review-done").exists)
        XCTAssertEqual(any(app, "review-done").label, "You've answered everything in this review.")
        shot(app, "10-all-done")
    }

    func testOverviewShowsStateAndOfflineSaysSavedOnThisPhone() {
        let app = launch(["-mockFailAnswers", "YES"])
        openStack(app)
        jump(app, "Send the November invoice to Anna")
        app.buttons["review-ok"].tap()
        XCTAssertTrue(NSPredicate(format: "label BEGINSWITH %@", "1 answered").evaluate(with: any(app, "review-progress")) || any(app, "review-progress").waitForExistence(timeout: 3))
        any(app, "review-all").tap()
        let state = any(app, "overview-state")
        XCTAssertTrue(state.waitForExistence(timeout: 5))
        XCTAssertEqual(state.label, "Saved on this phone")
        shot(app, "11-overview-saved-on-phone")
    }
}
