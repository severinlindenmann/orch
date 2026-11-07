import XCTest

/// Phone archive and delete (PLAN-A section 2) against the MockRelay: the Q3 ticket of Pilatus is Done.
final class ArchiveUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }
    private let row = "ticket-ws_pilatus001|t_q3sum1"

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-openChat", "ws_pilatus001"]
        app.launch()
        let done = app.buttons["segment-done"]
        XCTAssertTrue(done.waitForExistence(timeout: 20), "workspace screen")
        done.tap()
        return app
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    func testSwipeArchiveUndoThenArchivedListMoveBack() {
        let app = launch()
        let chat = el(app, row)
        XCTAssertTrue(chat.waitForExistence(timeout: 20))
        chat.swipeLeft()
        XCTAssertTrue(app.buttons["Delete"].exists, "Done chat offers Delete")
        app.buttons["Archive"].tap()
        XCTAssertTrue(el(app, "archive-toast").waitForExistence(timeout: 5))
        el(app, "archive-undo").tap()
        XCTAssertTrue(chat.waitForExistence(timeout: 5), "Undo brings the chat back")
        chat.swipeLeft(); app.buttons["Archive"].tap()
        XCTAssertTrue(chat.waitForNonExistence(timeout: 5), "the row is gone")
        let archived = el(app, "archived-row")
        XCTAssertTrue(archived.waitForExistence(timeout: 5)); archived.tap()
        XCTAssertTrue(el(app, "archived-t:ws_pilatus001|t_q3sum1").waitForExistence(timeout: 5))
        el(app, "move-back-t:ws_pilatus001|t_q3sum1").tap()
        XCTAssertTrue(el(app, "archived-t:ws_pilatus001|t_q3sum1").waitForNonExistence(timeout: 5))
    }

    func testDeleteAsksInPlainWordsAndErasesThisPhonesCopy() {
        let app = launch()
        let chat = el(app, row)
        XCTAssertTrue(chat.waitForExistence(timeout: 20))
        chat.swipeLeft(); app.buttons["Delete"].tap()
        XCTAssertTrue(app.staticTexts["Delete this chat from your phone?"].waitForExistence(timeout: 5))
        el(app, "delete-confirm").tap()
        XCTAssertTrue(chat.waitForNonExistence(timeout: 5), "the chat leaves the list")
        XCTAssertFalse(el(app, "archived-row").exists, "a deleted chat is not archived")
    }

    func testAutoArchiveSwitchInSettings() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-startTab", "settings"]
        app.launch()
        let toggle = el(app, "auto-archive")
        XCTAssertTrue(toggle.waitForExistence(timeout: 20))
        toggle.tap()
        let days = el(app, "auto-archive-days")
        XCTAssertTrue(days.waitForExistence(timeout: 5)); days.tap()
        el(app, "auto-archive-14").tap()
        app.navigationBars.buttons.firstMatch.tap()
        XCTAssertTrue(app.staticTexts["14 days"].waitForExistence(timeout: 5))
    }
}
