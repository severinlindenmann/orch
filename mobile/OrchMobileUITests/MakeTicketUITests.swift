import XCTest

final class MakeTicketUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    func testMakeTicket() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES",
                                "-mockMakeTicket", "YES", "-openChat", "ws_pilatus001"]
        app.launch()
        let general = app.buttons["general-ws_pilatus001"]
        XCTAssertTrue(general.waitForExistence(timeout: 20))
        general.tap()
        let card = app.descendants(matching: .any)["make-ticket-card"].firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 10))
        let make = app.buttons["make-ticket"]
        XCTAssertTrue(make.waitForExistence(timeout: 10))
        make.tap()
        XCTAssertTrue(card.staticTexts["Ticket made"].waitForExistence(timeout: 10))
        XCTAssertFalse(make.exists)
        XCTAssertFalse(app.buttons["make-ticket-not-now"].exists)
    }
}
