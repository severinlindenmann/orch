import XCTest

/// Results section on the ticket info screen (draft 02, 2.6) beyond TicketResultsUITests: no results, a trimmed result
/// (as the workspace sends it: table cut with total_rows, link without query, closing "More on the computer").
final class ResultsSectionUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func openInfo(_ ws: String, _ ticket: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES",
                                "-openChat", ws, "-openTicket", ticket, "-openInfo", "YES"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["info-summary"].firstMatch.waitForExistence(timeout: 20))
        return app
    }

    func testTicketWithoutResultsShowsNoSection() {
        let app = openInfo("ws_reports001", "t_9k2m4q")
        // Give the screen a moment to settle, then make sure no Results header or result card appears anywhere.
        XCTAssertTrue(app.descendants(matching: .any)["info-shared"].firstMatch.waitForExistence(timeout: 10))   // a lone filter shows no tab
        XCTAssertFalse(app.staticTexts["Results"].exists, "no Results header without results")
        XCTAssertFalse(app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'results-card-'")).firstMatch.exists)
    }

    func testTrimmedOrchResultShowsCutTableAndMoreOnTheComputer() {
        let app = openInfo("ws_pilatus001", "t_q3sum1")
        let card = app.buttons["results-card-a_dddddddddddd"]
        for _ in 0..<6 where !card.isHittable { app.swipeUp() }
        XCTAssertTrue(card.isHittable, "the oldest result card is listed (collapsed)")
        let label = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "Worked out by orch")).firstMatch
        XCTAssertTrue(label.exists, "orch label")
        XCTAssertFalse(app.staticTexts["Checked invoices"].exists, "collapsed: table not shown yet")
        card.tap()
        let footer = app.staticTexts["20 of 45 rows"]
        for _ in 0..<6 where !footer.exists { app.swipeUp() }
        XCTAssertTrue(footer.waitForExistence(timeout: 5), "cut table says how many rows the computer has")
        let more = app.staticTexts["More on the computer"]
        for _ in 0..<4 where !more.isHittable { app.swipeUp() }
        XCTAssertTrue(more.exists, "closing summary of a trimmed result")
        // A SwiftUI Link is exposed as a link element.
        XCTAssertTrue(app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Invoice list")).firstMatch.exists, "link block label shown")
    }
}
