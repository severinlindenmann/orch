import XCTest

final class ReviewBarUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-mockReview", "YES",
                                "-openChat", "ws_pilatus001", "-openTicket", "t_reviewfish"]
        app.launch()
        return app
    }
    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any)[id].firstMatch
    }
    func testAcceptClosesReviewBar() {
        let app = launch()
        let bar = element(app, "review-bar")
        XCTAssertTrue(bar.waitForExistence(timeout: 20))
        XCTAssertTrue(app.buttons["review-accept"].exists)
        XCTAssertTrue(app.buttons["review-changes"].exists)
        XCTAssertFalse(app.staticTexts["Is this done?"].exists)
        app.buttons["review-accept"].tap()
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: bar)
        XCTAssertEqual(XCTWaiter.wait(for: [gone], timeout: 10), .completed)
    }
    func testChangesFocusesAnswerComposer() {
        let app = launch()
        XCTAssertTrue(app.buttons["review-changes"].waitForExistence(timeout: 20))
        app.buttons["review-changes"].tap()
        XCTAssertTrue(app.staticTexts["Changes:"].waitForExistence(timeout: 5))
        let field = element(app, "composer-field")
        XCTAssertEqual(field.placeholderValue, "What should change?")
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
        field.typeText("Make the heading blue")
        XCTAssertTrue((field.value as? String ?? "").contains("Make the heading blue"))
    }
}
