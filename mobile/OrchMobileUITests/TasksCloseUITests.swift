import XCTest

/// The Tasks sheet's close button is a real accessible button (VoiceOver can reach it, not only the sheet grabber).
final class TasksCloseUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    @MainActor
    func testTasksSheetCloseIsAnAccessibleButton() {
        let app = XCUIApplication()
        app.launchArguments = ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES",
                               "-openChat", "ws_reports001", "-openTicket", "t_9k2m4q"]
        app.launch()
        let toggle = app.descendants(matching: .any)["tasks-toggle"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 20))
        toggle.tap()
        let close = app.buttons["tasks-close"]
        XCTAssertTrue(close.waitForExistence(timeout: 10), "close button exposed as a button")
        XCTAssertEqual(close.label, "Close tasks")
        XCTAssertTrue(close.isHittable)
        close.tap()
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: close)
        XCTAssertEqual(XCTWaiter.wait(for: [gone], timeout: 10), .completed, "sheet closed")
    }
}
