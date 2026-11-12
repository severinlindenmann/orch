import XCTest

final class DoneReviewUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch(ticket: String? = nil) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES",
                                "-mockDoneReview", "YES", "-openChat", "ws_pilatus001"]
        if let ticket { app.launchArguments += ["-openTicket", ticket] }
        app.launch()
        return app
    }

    private func assertReviewStatus(_ app: XCUIApplication) {
        XCTAssertTrue(app.descendants(matching: .any)["tasks-toggle"].firstMatch.waitForExistence(timeout: 20))
        let status = app.staticTexts["Ready for review"].firstMatch
        XCTAssertTrue(status.waitForExistence(timeout: 10))
        XCTAssertTrue(status.isHittable)
        XCTAssertEqual(status.label, "Ready for review")
        XCTAssertFalse(app.staticTexts["Done"].exists)
    }

    func testDoneWithVerdictQuestionShowsReviewBar() {
        let app = launch(ticket: "t_donerev1")
        assertReviewStatus(app)
        XCTAssertTrue(app.descendants(matching: .any)["review-bar"].firstMatch.waitForExistence(timeout: 10))
        for (id, label) in [("review-accept", "Accept"), ("review-changes", "Ask for changes")] {
            let button = app.buttons[id]
            XCTAssertTrue(button.waitForExistence(timeout: 10))
            XCTAssertEqual(button.label, label)
            XCTAssertTrue(button.isHittable)
        }
    }

    func testDoneWithoutQuestionShowsReviewOnly() {
        let app = launch(ticket: "t_donerev2")
        assertReviewStatus(app)
        for id in ["review-bar", "review-accept", "review-changes"] {
            let element = app.descendants(matching: .any)[id].firstMatch
            let absent = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: element)
            XCTAssertEqual(XCTWaiter.wait(for: [absent], timeout: 5), .completed)
        }
    }

    func testDoneResultsShowReviewInTopicList() {
        let app = launch()
        XCTAssertTrue(app.buttons["general-ws_pilatus001"].waitForExistence(timeout: 20))
        for (id, title) in [("t_donerev1", "Done, verdict asked"), ("t_donerev2", "Done, no question")] {
            let row = app.buttons["ticket-ws_pilatus001|" + id]
            XCTAssertTrue(row.waitForExistence(timeout: 10))
            let review = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS %@", "Ready for review"), object: row)
            XCTAssertEqual(XCTWaiter.wait(for: [review], timeout: 10), .completed)
            XCTAssertTrue(row.isHittable)
            XCTAssertTrue(row.label.contains(title))
            // The fixture title itself says Done; only the status must not say it.
            XCTAssertFalse(row.label.replacingOccurrences(of: title, with: "").contains("Done"))
        }
    }
}
