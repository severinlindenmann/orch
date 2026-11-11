import XCTest

/// W5-S: the workspace screen groups topics by status, and the info screen lists References.
final class StatusRefsUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch(_ chat: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-openChat", chat]
        app.launch()
        return app
    }
    private func shot(_ app: XCUIApplication, _ name: String) {
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        let dir = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/mobile-v3-messenger/build/shots/w5s")
        guard FileManager.default.fileExists(atPath: dir.path) else { return }
        try? app.screenshot().pngRepresentation.write(to: dir.appendingPathComponent("\(name).png"))
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    func testWorkspaceGroupsByStatusAndDoneIsCollapsed() {
        let app = launch("ws_pilatus001")
        XCTAssertTrue(app.buttons["general-ws_pilatus001"].waitForExistence(timeout: 20), "General is pinned")
        XCTAssertTrue(app.staticTexts["Needs you"].waitForExistence(timeout: 10), "the topic with an open question is under Needs you")
        XCTAssertTrue(app.buttons["ticket-ws_pilatus001|t_7k3f9q"].exists)
        XCTAssertFalse(app.staticTexts["Not started"].exists && app.staticTexts["Ready for review"].exists, "empty groups are hidden")
        let done = app.buttons["done-toggle"]
        XCTAssertTrue(done.exists)
        XCTAssertFalse(app.buttons["ticket-ws_pilatus001|t_q3sum1"].exists, "Done is collapsed")
        shot(app, "1-workspace-groups")
        done.tap()
        let q3 = app.buttons["ticket-ws_pilatus001|t_q3sum1"]
        XCTAssertTrue(q3.waitForExistence(timeout: 5))
        app.reveal(q3)
        XCTAssertFalse(app.staticTexts["Done"].exists, "Done is shown once: the toggle, no second header above the rows")
        XCTAssertLessThan(done.frame.minY, q3.frame.minY, "the finished chat sits under the toggle")
        shot(app, "2-workspace-done-open")
    }

    func testWorkingGroupShowsTheChip() {
        let app = launch("ws_reports001")
        XCTAssertTrue(app.staticTexts["Working · 1"].waitForExistence(timeout: 20), "group header with its count")
        XCTAssertTrue(app.buttons["ticket-ws_reports001|t_9k2m4q"].exists)
        XCTAssertTrue(app.staticTexts["Claude is working"].exists)
        XCTAssertFalse(app.buttons["done-toggle"].exists, "no finished topic, no Done group")
        shot(app, "3-workspace-working")
    }

    func testInfoScreenListsReferences() {
        let app = launch("ws_pilatus001")
        XCTAssertTrue(app.buttons["done-toggle"].waitForExistence(timeout: 20))
        app.buttons["done-toggle"].tap()
        let q3 = app.buttons["ticket-ws_pilatus001|t_q3sum1"]
        XCTAssertTrue(q3.waitForExistence(timeout: 5))
        app.reveal(q3)
        q3.tap()
        let info = el(app, "chat-info")
        XCTAssertTrue(info.waitForExistence(timeout: 10)); info.tap()
        let tab = app.buttons["info-tab-links"]
        XCTAssertTrue(tab.waitForExistence(timeout: 10))
        XCTAssertTrue(tab.label.hasPrefix("References"), tab.label)
        tab.tap()
        // The Results section (draft 02, 2.6) sits above the references and the list is lazy: scroll down to them.
        for _ in 0..<4 where !el(app, "info-ref-ref0").exists { app.swipeUp() }
        XCTAssertTrue(el(app, "info-ref-ref0").waitForExistence(timeout: 5), "web address card")
        XCTAssertTrue(app.staticTexts["PIL-13 · Rename field X in ingestion job"].exists, "ticket row with key and title")
        for _ in 0..<3 where !app.staticTexts["docs/board/q3.md:12"].exists { app.swipeUp() }   // the list is lazy
        XCTAssertTrue(app.staticTexts["docs/board/q3.md:12"].waitForExistence(timeout: 5), "file reference as plain text")
        shot(app, "4-references")
        for _ in 0..<3 where !el(app, "info-ref-ref1").isHittable { app.swipeDown() }
        el(app, "info-ref-ref1").tap()   // opens that topic
        // The referenced topic opened: its ticket chat status line (tasks toggle); "tasks-card" no longer exists.
        XCTAssertTrue(app.descendants(matching: .any)["tasks-toggle"].waitForExistence(timeout: 10))
        shot(app, "5-reference-opened")
    }

    /// Scrolled to the very bottom (Done open), the last row ends above the pinned "New topic" bar.
    func testLastRowClearsTheNewTopicBar() {
        let app = launch("ws_pilatus001")
        XCTAssertTrue(app.buttons["done-toggle"].waitForExistence(timeout: 20))
        app.buttons["done-toggle"].tap()
        let last = app.buttons["ticket-ws_pilatus001|t_q3sum1"]
        XCTAssertTrue(last.waitForExistence(timeout: 5))
        for _ in 0..<5 { app.swipeUp() }
        let bar = app.buttons["New topic"]
        XCTAssertTrue(bar.exists)
        XCTAssertLessThanOrEqual(last.frame.maxY, bar.frame.minY, "the last row is fully above the bar")
        shot(app, "6-workspace-bottom")
        last.tap()   // opens the topic, not the New topic sheet
        XCTAssertTrue(app.descendants(matching: .any)["chat-info"].waitForExistence(timeout: 10))
    }

    /// Mobile mode off: no empty banner row. General sits right below the header (workspace screen) and the search field right
    /// below the title row (chats list).
    func testNoEmptyBannerGapWithMobileModeOff() {
        let app = launch("ws_pilatus001")
        let general = app.buttons["general-ws_pilatus001"]
        XCTAssertTrue(general.waitForExistence(timeout: 20))
        XCTAssertFalse(app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'mobile-mode-banner-'")).firstMatch.exists)
        let nav = app.navigationBars.firstMatch
        XCTAssertLessThan(general.frame.minY - nav.frame.maxY, 40, "General sits right below the header")
        shot(app, "7-workspace-no-gap")
        app.terminate()

        let chats = XCUIApplication()
        chats.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"]
        chats.launch()
        let search = el(chats, "chat-search"), top = el(chats, "new-chat")
        XCTAssertTrue(search.waitForExistence(timeout: 20))
        XCTAssertLessThan(search.frame.minY - top.frame.maxY, 40, "search sits right below the title row")
        shot(chats, "8-chats-no-gap")
    }
}
