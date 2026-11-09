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
    func testChangesSubmitClosesReviewBar() {
        let app = launch()
        let bar = element(app, "review-bar")
        XCTAssertTrue(bar.waitForExistence(timeout: 20))
        app.buttons["review-changes"].tap()
        let field = element(app, "composer-field")
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
        field.typeText("Make the heading blue")
        app.buttons["composer-send"].tap()
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: bar)
        XCTAssertEqual(XCTWaiter.wait(for: [gone], timeout: 10), .completed)
        // Our own answer closes the question mid-send: answering mode must end cleanly, no "closed" message, field empty.
        XCTAssertFalse(app.staticTexts["This question is already answered."].exists)
        XCTAssertFalse(app.staticTexts["This review was updated."].exists)
        XCTAssertFalse(app.staticTexts["This review is closed."].exists)
        XCTAssertEqual((field.value as? String) ?? "", field.placeholderValue ?? "")
    }

    func testReservedChangeNoteKeepsReviewOpen() {
        let app = launch()
        XCTAssertTrue(app.buttons["review-changes"].waitForExistence(timeout: 20))
        app.buttons["review-changes"].tap()
        let field = element(app, "composer-field")
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
        field.typeText("accept")
        app.buttons["composer-send"].tap()
        XCTAssertTrue(app.staticTexts["Write what should change."].waitForExistence(timeout: 5))
        XCTAssertTrue(element(app, "review-bar").exists)
        XCTAssertEqual(field.value as? String, "accept")
    }

    func testEmptyChangeNoteKeepsReviewOpen() {
        let app = launch()
        XCTAssertTrue(app.buttons["review-changes"].waitForExistence(timeout: 20))
        app.buttons["review-changes"].tap()
        app.buttons["composer-send"].tap()
        XCTAssertTrue(element(app, "review-bar").exists)
        XCTAssertTrue(app.staticTexts["Changes:"].exists)
    }

}
