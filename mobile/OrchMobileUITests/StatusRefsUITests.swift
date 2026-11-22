import XCTest

/// W5-S: ticket chats show their status on Chats (they left the workspace screen, owner 21 Nov, ORCH-1169), and the info screen lists References.
final class StatusRefsUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch(_ chat: String?) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"] + (chat.map { ["-openChat", $0] } ?? [])
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

    func testTicketChatsShowStatusAndDoneIsCollapsed() {
        let app = launch(nil)
        let open = app.buttons["ticket-ws_pilatus001|t_7k3f9q"]
        XCTAssertTrue(open.waitForExistence(timeout: 20), "the ticket chat with an open question is on Chats")
        XCTAssertTrue(open.label.contains("Needs your OK"), open.label)
        XCTAssertTrue(app.buttons["ticket-ws_reports001|t_9k2m4q"].exists, "a working ticket chat too")
        let done = app.buttons["done-toggle"]
        XCTAssertTrue(done.exists)
        XCTAssertFalse(app.buttons["ticket-ws_pilatus001|t_q3sum1"].exists, "Done is collapsed")
        shot(app, "1-ticket-chats")
        app.reveal(done); done.tap()
        let q3 = app.buttons["ticket-ws_pilatus001|t_q3sum1"]
        XCTAssertTrue(q3.waitForExistence(timeout: 5))
        app.reveal(q3)
        XCTAssertLessThan(done.frame.minY, q3.frame.minY, "the finished chat sits under the toggle")
        shot(app, "2-ticket-chats-done-open")
    }

    func testWorkspaceScreenListsNoTopics() {
        let app = launch("ws_reports001")
        XCTAssertTrue(app.buttons["general-ws_reports001"].waitForExistence(timeout: 20))
        XCTAssertFalse(app.buttons["ticket-ws_reports001|t_9k2m4q"].exists)
        XCTAssertFalse(app.buttons["done-toggle"].exists)
        XCTAssertTrue(app.buttons["New topic"].exists, "a new topic still starts here")
        shot(app, "3-workspace-general-only")
    }

    func testInfoScreenListsReferences() {
        let app = launch(nil)
        XCTAssertTrue(app.buttons["done-toggle"].waitForExistence(timeout: 20))
        app.reveal(app.buttons["done-toggle"]); app.buttons["done-toggle"].tap()
        let q3 = app.buttons["ticket-ws_pilatus001|t_q3sum1"]
        XCTAssertTrue(q3.waitForExistence(timeout: 5))
        app.reveal(q3)
        q3.tap()
        let info = el(app, "chat-info")
        XCTAssertTrue(info.waitForExistence(timeout: 10)); info.tap()
        let tab = app.buttons["info-tab-links"]
        XCTAssertTrue(tab.waitForExistence(timeout: 10))
        XCTAssertTrue(tab.label.hasPrefix("Links"), tab.label)
        tab.tap()
        // The Results section (draft 02, 2.6) sits above the references and the list is lazy: scroll down to them.
        for _ in 0..<4 where !el(app, "info-ref-ref0").exists { app.swipeUp() }
        XCTAssertTrue(el(app, "info-ref-ref0").waitForExistence(timeout: 5), "web address card")
        let ticketRow = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "Rename field X in ingestion job")).firstMatch
        for _ in 0..<3 where !ticketRow.exists { app.swipeUp() }
        XCTAssertTrue(ticketRow.waitForExistence(timeout: 5), "ticket row with title (key behind Details)")
        let fileReference = el(app, "info-ref-ref3")
        app.reveal(fileReference)
        // The Details disclosure may be the element itself (SwiftUI folds the id onto the disclosure button).
        let details = fileReference.buttons["Details"]
        if details.exists { details.tap() } else { fileReference.tap() }
        XCTAssertTrue(app.staticTexts["docs/board/q3.md:12"].waitForExistence(timeout: 5), "file reference under Details")
        shot(app, "4-references")
        for _ in 0..<3 where !el(app, "info-ref-ref1").isHittable { app.swipeDown() }
        el(app, "info-ref-ref1").tap()   // opens that topic
        // The referenced topic opened: its ticket chat status line (tasks toggle); "tasks-card" no longer exists.
        // The referenced topic opened: a ticket chat (conversation view) with that topic's title in its header.
        XCTAssertTrue(app.descendants(matching: .any)["conversation-view"].firstMatch.waitForExistence(timeout: 10))
        let openedTitle = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "Rename field X in ingestion job")).firstMatch
        XCTAssertTrue(openedTitle.waitForExistence(timeout: 10), "the referenced topic's chat is open")
        shot(app, "5-reference-opened")
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
