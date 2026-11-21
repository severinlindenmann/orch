import XCTest

/// Team chat step 2 (ORCH-1175): in a ticket chat the person sees who is in it, adds a workspace from the Add sheet
/// (Workspaces), sees other workspaces' names on their messages, chat info with who added whom and the older orch mark,
/// and answers the helper's Add / Not now card. Screenshots go to ORCH_SHOTS_DIR when it is set
/// (xcodebuild: TEST_RUNNER_ORCH_SHOTS_DIR=<folder>).
final class TeamChatUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    private func launch(_ extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES",
                                "-mockTicketChat", "YES", "-mockTeamChat", "YES"] + extra
        app.launch()
        return app
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }
    private func shot(_ app: XCUIApplication, _ name: String) throws {
        let png = app.screenshot().pngRepresentation
        let attachment = XCTAttachment(data: png, uniformTypeIdentifier: "public.png")
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
        if let dir = ProcessInfo.processInfo.environment["ORCH_SHOTS_DIR"], !dir.isEmpty {
            try png.write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(name).png"))
        }
    }
    private func openTicketChat(_ app: XCUIApplication) {
        let row = el(app, "ticket-chat-ws_pilatus001|t_7k3f9q")
        XCTAssertTrue(row.waitForExistence(timeout: 20), "PIL-13 is in Ticket chats")
        row.tap()
        XCTAssertTrue(el(app, "team-chat-members").waitForExistence(timeout: 15), "the strip shows who is in the chat")
    }

    func testNamesChatInfoAndAddSheet() throws {
        let app = launch()
        openTicketChat(app)
        let strip = el(app, "team-chat-members")
        XCTAssertTrue(strip.label.contains("Pilatus Workspace, Sales and Bank"), strip.label)
        // Another workspace's message carries its name.
        let sales = el(app, "chat-sender-m_teamsales0000001")
        XCTAssertTrue(sales.waitForExistence(timeout: 10), "a message from Sales shows in the ticket chat")
        XCTAssertTrue(sales.label.contains("Helper · Sales"), sales.label)
        try shot(app, "team-chat-names")

        // Chat info: who added whom, and the older orch mark.
        strip.tap()
        let salesRow = el(app, "team-info-member-ws_sales00001")
        XCTAssertTrue(salesRow.waitForExistence(timeout: 10))
        XCTAssertTrue(salesRow.label.contains("Added by you"), salesRow.label)
        let bankRow = el(app, "team-info-member-ws_bank000001")
        XCTAssertTrue(bankRow.label.contains("Added by Pilatus Workspace"), bankRow.label)
        XCTAssertTrue(bankRow.label.contains("older orch"), bankRow.label)
        XCTAssertFalse(salesRow.label.contains("older orch"))
        try shot(app, "team-chat-info")

        // Add sheet: the Workspaces list with the one-line notice; Add asks the ticket's workspace.
        el(app, "team-info-add").tap()
        XCTAssertTrue(el(app, "team-add-tab-workspaces").waitForExistence(timeout: 10))
        XCTAssertTrue(el(app, "team-add-notice").label.contains("They see this ticket and the whole chat."))
        let add = el(app, "team-add-ws_reports001")
        XCTAssertTrue(add.exists, "Reports (on this phone, not in the chat) can be added")
        XCTAssertFalse(el(app, "team-add-ws_pilatus001").exists, "the ticket's workspace is not offered")
        try shot(app, "team-chat-add-sheet")
        add.tap()
        XCTAssertTrue(el(app, "team-add-asked").waitForExistence(timeout: 10))
        try shot(app, "team-chat-add-asked")
        el(app, "team-add-done").tap()
        // The workspace's change reached the phone: Reports is a member, added by you.
        let reports = el(app, "team-info-member-ws_reports001")
        XCTAssertTrue(reports.waitForExistence(timeout: 20), "Reports joined the chat")
        XCTAssertTrue(reports.label.contains("Added by you"), reports.label)
        try shot(app, "team-chat-info-after-add")
    }

    func testHelpersAskCardAddsTheWorkspace() throws {
        let app = launch()
        openTicketChat(app)
        let add = el(app, "answer-Add")
        XCTAssertTrue(add.waitForExistence(timeout: 15), "the helper's ask card shows Add")
        XCTAssertTrue(el(app, "answer-Not now").exists, "and Not now")
        try shot(app, "team-chat-ask-card")
        add.tap()
        // After the undo window the answer goes; the workspace adds Reports and the strip names it.
        let strip = el(app, "team-chat-members")
        var named = false
        for _ in 0..<30 where !named {
            named = strip.label.contains("and 2 more") || strip.label.contains("Reports")
            if !named { Thread.sleep(forTimeInterval: 1) }
        }
        XCTAssertTrue(named, strip.label)
        try shot(app, "team-chat-ask-card-added")
    }

    func testAnOlderRelaySaysAddOnTheComputer() throws {
        let app = launch(["-mockOldRelay", "YES"])
        openTicketChat(app)
        el(app, "team-chat-add").tap()
        let add = el(app, "team-add-ws_reports001")
        XCTAssertTrue(add.waitForExistence(timeout: 10))
        add.tap()
        let error = el(app, "team-add-error")
        XCTAssertTrue(error.waitForExistence(timeout: 10))
        XCTAssertEqual(error.label, "Adding from the phone is not ready yet. Add it on the computer.")
    }
}
