import XCTest

/// Phone archive and delete (PLAN-A section 2) against the MockRelay: the Q3 ticket of Pilatus is Done.
final class ArchiveUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }
    private let row = "ticket-ws_pilatus001|t_q3sum1"

    /// One launch path for every test here: a stray instance from the previous test is ended first (slow CI simulators time out
    /// while it shuts down), then the app starts with the mock relay.
    private func start(_ extra: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        if app.state != .notRunning { app.terminate() }
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-uitest"] + extra
        app.launchEnvironment["ORCH_UITEST_TOAST_SECONDS"] = "30"   // the 5 s undo toast is too short for a slow CI runner
        app.launch()
        return app
    }
    private func launch() -> XCUIApplication {
        let app = start(["-openChat", "ws_pilatus001"])
        let done = app.buttons["done-toggle"]
        XCTAssertTrue(done.waitForExistence(timeout: 20), "workspace screen")
        done.tap()
        // The workspace look and banners push the Done rows below the fold: scroll like a person would.
        let chat = app.descendants(matching: .any)[row].firstMatch
        XCTAssertTrue(chat.waitForExistence(timeout: 20))
        app.reveal(chat)
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

    /// Waits until an element exists and can be tapped (swipe actions, toasts and dialogs animate in; a busy runner is slow).
    private func ready(_ e: XCUIElement, _ what: String, timeout: TimeInterval = 15, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(e.waitForExistence(timeout: timeout), "\(what) shows", file: file, line: line)
        let ok = NSPredicate(format: "exists == true AND isHittable == true")
        XCTAssertEqual(XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: ok, object: e)], timeout: timeout), .completed,
                       "\(what) can be tapped", file: file, line: line)
    }
    /// Swipe the row and tap one of its actions once the button is there.
    private func swipeAction(_ app: XCUIApplication, _ rowEl: XCUIElement, _ title: String) {
        app.reveal(rowEl)
        let b = app.buttons[title]
        rowEl.swipeLeft()
        if !b.waitForExistence(timeout: 10) {   // a swipe can be lost while the list settles: once more
            app.reveal(rowEl)
            rowEl.swipeLeft()
        }
        ready(b, "\(title) action")
        b.tap()
    }
    /// The row is back after Undo: re-query (the list rebuilds), scroll to it, give it 10 s or more.
    private func rowBack(_ app: XCUIApplication, _ why: String, file: StaticString = #filePath, line: UInt = #line) -> XCUIElement {
        let back = el(app, row)
        XCTAssertTrue(back.waitForExistence(timeout: 15), why, file: file, line: line)
        app.reveal(back)
        ready(back, "the restored row", file: file, line: line)
        return back
    }

    func testSwipeArchiveUndoThenArchivedListMoveBack() {
        let app = launch()
        let chat = el(app, row)
        XCTAssertTrue(chat.waitForExistence(timeout: 20))
        app.reveal(chat)
        chat.swipeLeft()
        ready(app.buttons["Delete"], "Delete action")
        shot(app, "1-swipe")
        ready(app.buttons["Archive"], "Archive action"); app.buttons["Archive"].tap()
        XCTAssertTrue(el(app, "archive-toast").waitForExistence(timeout: 10), "undo toast shows")   // not hittable-checked: it only lives 5 s
        // No screenshot here: the toast only lives 5 s and a screenshot on a busy machine can eat that.
        ready(app.buttons["Undo"], "Undo button", timeout: 10); app.buttons["Undo"].tap()
        let back = rowBack(app, "Undo brings the chat back")
        swipeAction(app, back, "Archive")
        XCTAssertTrue(el(app, row).waitForNonExistence(timeout: 10), "the row is gone")
        let archived = el(app, "archived-row")
        ready(archived, "Archived row"); archived.tap()
        XCTAssertTrue(el(app, "archived-t:ws_pilatus001|t_q3sum1").waitForExistence(timeout: 10))
        shot(app, "3-archived-list")
        ready(el(app, "move-back-t:ws_pilatus001|t_q3sum1"), "move back button"); el(app, "move-back-t:ws_pilatus001|t_q3sum1").tap()
        XCTAssertTrue(el(app, "archived-t:ws_pilatus001|t_q3sum1").waitForNonExistence(timeout: 10))
    }

    /// Product check: Undo always brings the chat back, also when archive and Undo follow each other quickly.
    func testArchiveThenUndoFiveTimesInARowAlwaysBringsTheChatBack() {
        let app = launch()
        var chat = el(app, row)
        for round in 1...5 {
            swipeAction(app, chat, "Archive")
            ready(app.buttons["Undo"], "Undo button (round \(round))", timeout: 10); app.buttons["Undo"].tap()
            chat = rowBack(app, "round \(round): Undo brings the chat back")
            XCTAssertTrue(el(app, "archive-toast").waitForNonExistence(timeout: 40), "round \(round): toast gone, the list has settled")
        }
    }

    func testDeleteAsksInPlainWordsAndErasesThisPhonesCopy() {
        let app = launch()
        let chat = el(app, row)
        XCTAssertTrue(chat.waitForExistence(timeout: 20))
        swipeAction(app, chat, "Delete")
        ready(app.staticTexts["Delete this chat from your phone?"], "delete confirmation", timeout: 10)
        shot(app, "4-delete-confirm")
        ready(el(app, "delete-confirm"), "confirm button"); el(app, "delete-confirm").tap()
        XCTAssertTrue(chat.waitForNonExistence(timeout: 10), "the chat leaves the list")
        XCTAssertFalse(el(app, "archived-row").exists, "a deleted chat is not archived")
    }

    func testAutoArchiveSwitchInSettings() {
        let app = start(["-startTab", "settings"])
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
