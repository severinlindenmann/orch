import XCTest

/// Team chat step 1 (ORCH-1169): Chats lists the ticket chats next to the workspaces; a ticket chat names who wrote
/// each message and keeps its question card and composer. Screenshots go to ORCH_SHOTS_DIR when it is set
/// (xcodebuild: TEST_RUNNER_ORCH_SHOTS_DIR=<folder>).
final class TicketChatsUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    private func launch(_ extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-mockTicketChat", "YES"] + extra
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

    /// Owner 21 Nov (q3): a ticket chat opened from Chats keeps everything the topic chat had: photo, file, location
    /// and voice in the box to write, and the chat's info with its Photos, Files and Links.
    func testTicketChatKeepsAttachmentsAndInfo() throws {
        let app = launch(["-fakePhoto", "YES", "-fakeLocation", "YES"])
        let row = el(app, "ticket-ws_pilatus001|t_7k3f9q")
        XCTAssertTrue(row.waitForExistence(timeout: 20), "the ticket chat is on Chats")
        app.reveal(row); row.tap()
        let plus = el(app, "composer-attach")
        XCTAssertTrue(plus.waitForExistence(timeout: 15), "the + for attachments")
        XCTAssertTrue(el(app, "composer-mic").exists, "the microphone for a voice message")

        // Photo.
        plus.tap()
        XCTAssertTrue(app.buttons["media-fake-photo"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["media-fake-pdf"].exists, "Files")
        XCTAssertTrue(app.buttons["media-location"].exists, "Location")
        try shot(app, "ticket-chat-attach")
        app.buttons["media-fake-photo"].tap()
        XCTAssertTrue(app.buttons["media-send"].waitForExistence(timeout: 5)); app.buttons["media-send"].tap()
        let image = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'image-'")).firstMatch
        XCTAssertTrue(image.waitForExistence(timeout: 15), "the photo shows in the ticket chat")

        // File: goes out at once.
        plus.tap()
        XCTAssertTrue(app.buttons["media-fake-pdf"].waitForExistence(timeout: 5)); app.buttons["media-fake-pdf"].tap()
        let file = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'file-'")).firstMatch
        XCTAssertTrue(file.waitForExistence(timeout: 15), "the file shows in the ticket chat")

        // Location.
        plus.tap()
        XCTAssertTrue(app.buttons["media-location"].waitForExistence(timeout: 5)); app.buttons["media-location"].tap()
        XCTAssertTrue(app.buttons["media-send"].waitForExistence(timeout: 10)); app.buttons["media-send"].tap()
        XCTAssertTrue(app.buttons["Open in Maps"].waitForExistence(timeout: 15), "the place shows in the ticket chat")
        try shot(app, "ticket-chat-attachments-sent")

        // The chat's info: Photos and Files of this ticket chat.
        el(app, "chat-info").tap()
        XCTAssertTrue(el(app, "info-tab-photos").waitForExistence(timeout: 10), "Photos in the ticket chat's info")
        XCTAssertTrue(el(app, "info-tab-files").exists, "Files in the ticket chat's info")
        try shot(app, "ticket-chat-info")
    }

    /// A ticket chat with the helper's results: its info lists Photos, Files and Links (as the topic info did).
    func testTicketChatInfoListsPhotosFilesAndLinks() throws {
        let app = launch(["-openChat", "ws_pilatus001", "-openTicket", "t_q3sum1"])
        let info = el(app, "chat-info")
        XCTAssertTrue(info.waitForExistence(timeout: 20)); info.tap()
        for tab in ["photos", "files", "links"] {
            XCTAssertTrue(el(app, "info-tab-\(tab)").waitForExistence(timeout: 10), "\(tab) in the ticket chat's info")
        }
        el(app, "info-tab-links").tap()
        try shot(app, "ticket-chat-info-links")
    }
}
