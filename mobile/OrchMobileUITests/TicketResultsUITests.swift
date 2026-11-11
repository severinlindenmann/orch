import XCTest

final class TicketResultsUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    func testResultsExpandAndOpenAttachment() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES",
                                "-openChat", "ws_pilatus001", "-openTicket", "t_q3sum1", "-openInfo", "YES"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["info-summary"].firstMatch.waitForExistence(timeout: 20))
        let checked = app.staticTexts["Checked by the helper"].firstMatch
        XCTAssertTrue(checked.waitForExistence(timeout: 10))
        app.reveal(checked)
        XCTAssertTrue(checked.isHittable)
        let summary = app.staticTexts["Q3 totals match the finance sheet."]
        app.reveal(summary)
        XCTAssertTrue(summary.isHittable, "Newest result starts expanded")
        XCTAssertFalse(app.staticTexts["Q3 export rows"].exists)
        let job = app.buttons["results-card-j_q3export"]
        app.reveal(job); job.tap()
        let table = app.staticTexts["Q3 export rows"]
        app.reveal(table)
        XCTAssertTrue(table.isHittable)
        XCTAssertTrue(app.staticTexts["3 of 40 rows"].exists)
        let file = app.buttons["Q3 chart"]
        for _ in 0..<6 where !file.isHittable { app.swipeDown() }
        XCTAssertTrue(file.isHittable)
        file.tap()
        XCTAssertTrue(app.buttons["artifact-close"].waitForExistence(timeout: 10))
    }
}
