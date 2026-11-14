import XCTest

final class NeedsYouHideUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func firstQuestionRow(_ app: XCUIApplication) -> XCUIElement {
        let predicate = NSPredicate(format: "identifier BEGINSWITH 'needs-you-' AND NOT identifier BEGINSWITH 'needs-you-hide' AND identifier != 'needs-you-see-all' AND identifier != 'needs-you-hidden'")
        return app.descendants(matching: .any).matching(predicate).firstMatch
    }

    func testSwipeHidesQuestionAndUndoRestoresIt() {
        let app = XCUIApplication()
        app.launchArguments = ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"]
        app.launchEnvironment["ORCH_UITEST_TOAST_SECONDS"] = "30"   // a slow CI runner: the toast must still be there to tap Undo
        app.launch()
        let row = firstQuestionRow(app)
        XCTAssertTrue(row.waitForExistence(timeout: 15))
        let id = row.identifier
        // A long drag across the row (from the right edge to the left edge): past the 55% "hide at once" mark, whatever the
        // swipe speed of this simulator. swipeLeft() alone can stop short and only reveal the Hide button.
        let start = row.coordinate(withNormalizedOffset: CGVector(dx: 0.92, dy: 0.5))
        let end = row.coordinate(withNormalizedOffset: CGVector(dx: 0.02, dy: 0.5))
        start.press(forDuration: 0.05, thenDragTo: end, withVelocity: .default, thenHoldForDuration: 0)
        // The Undo button is the toast's own control: it is what a person taps (the toast lives 5 s).
        let undo = app.buttons["hidden-undo"]
        XCTAssertTrue(undo.waitForExistence(timeout: 5), "the Hidden · Undo toast shows")
        XCTAssertFalse(app.descendants(matching: .any)[id].firstMatch.waitForExistence(timeout: 1), "row left the pinned section")
        undo.tap()
        XCTAssertTrue(app.descendants(matching: .any)[id].firstMatch.waitForExistence(timeout: 5), "Undo brings the row back")
    }
}
