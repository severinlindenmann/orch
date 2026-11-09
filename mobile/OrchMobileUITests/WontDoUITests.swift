import XCTest

final class WontDoUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    @MainActor
    func testInvoiceTasksShowWontDoReason() {
        let app = XCUIApplication()
        app.launchArguments = ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"]
        app.launch()
        let room = app.buttons["room-ws_reports001"]
        XCTAssertTrue(room.waitForExistence(timeout: 15))
        room.tap()
        let ticket = app.buttons["ticket-ws_reports001|t_9k2m4q"]
        XCTAssertTrue(ticket.waitForExistence(timeout: 10))
        ticket.tap()
        let tasks = app.descendants(matching: .any)["tasks-toggle"]
        XCTAssertTrue(tasks.waitForExistence(timeout: 10))
        tasks.tap()
        XCTAssertTrue(app.staticTexts["Won't do · Nobody uses it"].waitForExistence(timeout: 10))
    }
}
