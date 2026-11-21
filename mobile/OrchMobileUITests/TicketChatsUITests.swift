import XCTest

/// Team chat step 1 (ORCH-1169): Chats lists the ticket chats next to the workspaces; a ticket chat names who wrote
/// each message and keeps its question card and composer. Screenshots go to ORCH_SHOTS_DIR when it is set
/// (xcodebuild: TEST_RUNNER_ORCH_SHOTS_DIR=<folder>).
final class TicketChatsUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-mockTicketChat", "YES"]
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

    func testTicketChatsListAndTicketChatWithNames() throws {
        let app = launch()
        // Chats: "Ticket chats" with PIL-13 and the workspace chats under "Workspaces".
        let list = el(app, "ticket-chats")
        XCTAssertTrue(list.waitForExistence(timeout: 20), "the Ticket chats list shows on Chats")
        XCTAssertTrue(app.staticTexts["Ticket chats"].exists)
        XCTAssertTrue(app.staticTexts["Workspaces"].exists, "the workspace chats sit under their own heading")
        let row = el(app, "ticket-ws_pilatus001|t_7k3f9q")
        XCTAssertTrue(row.waitForExistence(timeout: 10))
        XCTAssertTrue(el(app, "room-ws_pilatus001").exists, "the workspace chat is still there")
        try shot(app, "ticket-chats-list")

        // The ticket chat: names above the incoming messages, the question card and the box to write.
        app.reveal(row); row.tap()
        let nina = el(app, "chat-sender-m_tcnina0000000001")
        XCTAssertTrue(nina.waitForExistence(timeout: 15), "a name typed on the computer shows above its message")
        XCTAssertTrue(nina.label.contains("Nina Weber · not signed in"), nina.label)
        let helper = el(app, "chat-sender-m_tcclaude00000002")
        XCTAssertTrue(helper.exists)
        XCTAssertTrue(helper.label.contains("Claude · "), helper.label)
        XCTAssertFalse(el(app, "chat-sender-m_tcyou00000000003").exists, "your own message has no name")
        XCTAssertTrue(app.staticTexts["Fine, pick what is safer."].exists)
        XCTAssertTrue(el(app, "answer-TIMESTAMP").waitForExistence(timeout: 10), "the question card with its options")
        XCTAssertTrue(el(app, "composer-field").exists, "the box to write")
        try shot(app, "ticket-chat-names")

        el(app, "answer-TIMESTAMP").tap()
        _ = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'undo-'")).firstMatch.waitForExistence(timeout: 5)
        try shot(app, "ticket-chat-answered")
    }
}
