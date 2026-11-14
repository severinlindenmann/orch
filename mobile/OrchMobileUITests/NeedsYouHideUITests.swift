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
        app.launch()
        let row = firstQuestionRow(app)
        XCTAssertTrue(row.waitForExistence(timeout: 15))
        let id = row.identifier
        row.swipeLeft()
        let toast = app.descendants(matching: .any)["hidden-toast"].firstMatch
        XCTAssertTrue(toast.waitForExistence(timeout: 5))
        XCTAssertFalse(app.descendants(matching: .any)[id].firstMatch.waitForExistence(timeout: 1), "row left the pinned section")
        app.buttons["hidden-undo"].tap()
        XCTAssertTrue(app.descendants(matching: .any)[id].firstMatch.waitForExistence(timeout: 5), "Undo brings the row back")
    }
}
