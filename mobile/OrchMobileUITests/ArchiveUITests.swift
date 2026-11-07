import XCTest

/// Phone archive and delete (PLAN-A section 2) against the MockRelay: the Q3 ticket of Pilatus is Done.
final class ArchiveUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }
    private let row = "ticket-ws_pilatus001|t_q3sum1"

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-openChat", "ws_pilatus001"]
        app.launch()
        let done = app.buttons["done-toggle"]
        XCTAssertTrue(done.waitForExistence(timeout: 20), "workspace screen")
        done.tap()
        return app
    }
    /// Evidence for the PR; only when the shots folder exists.
    private func shot(_ app: XCUIApplication, _ name: String) {
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        let dir = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/mobile-v3-messenger/build/shots/ar")
        guard FileManager.default.fileExists(atPath: dir.path) else { return }
        try? app.screenshot().pngRepresentation.write(to: dir.appendingPathComponent("\(name).png"))
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    func testSwipeArchiveUndoThenArchivedListMoveBack() {
        let app = launch()
        let chat = el(app, row)
        XCTAssertTrue(chat.waitForExistence(timeout: 20))
        chat.swipeLeft()
        XCTAssertTrue(app.buttons["Delete"].exists, "Done chat offers Delete")
        shot(app, "1-swipe")
        app.buttons["Archive"].tap()
        XCTAssertTrue(el(app, "archive-toast").waitForExistence(timeout: 5))
        shot(app, "2-undo-toast")
        app.buttons["Undo"].tap()
        XCTAssertTrue(chat.waitForExistence(timeout: 5), "Undo brings the chat back")
        chat.swipeLeft(); app.buttons["Archive"].tap()
        XCTAssertTrue(chat.waitForNonExistence(timeout: 5), "the row is gone")
        let archived = el(app, "archived-row")
        XCTAssertTrue(archived.waitForExistence(timeout: 5)); archived.tap()
        XCTAssertTrue(el(app, "archived-t:ws_pilatus001|t_q3sum1").waitForExistence(timeout: 5))
        shot(app, "3-archived-list")
        el(app, "move-back-t:ws_pilatus001|t_q3sum1").tap()
        XCTAssertTrue(el(app, "archived-t:ws_pilatus001|t_q3sum1").waitForNonExistence(timeout: 5))
    }

    func testDeleteAsksInPlainWordsAndErasesThisPhonesCopy() {
        let app = launch()
        let chat = el(app, row)
        XCTAssertTrue(chat.waitForExistence(timeout: 20))
        chat.swipeLeft(); app.buttons["Delete"].tap()
        XCTAssertTrue(app.staticTexts["Delete this chat from your phone?"].waitForExistence(timeout: 5))
        shot(app, "4-delete-confirm")
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
        shot(app, "5-auto-days")
        el(app, "auto-archive-14").tap()
        app.navigationBars.buttons.firstMatch.tap()
        XCTAssertTrue(app.staticTexts["14 days"].waitForExistence(timeout: 5))
    }
}
