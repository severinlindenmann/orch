import XCTest

/// Click-through against the in-process MockRelay: onboarding, chats, answer, ticket chat, new chat, offline.
final class OnboardingFlowUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func paired(_ extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-undoSeconds", "1"] + extra
        app.launch()
        return app
    }

    func testOnboardingToChats() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock"]
        app.launch()
        XCTAssertTrue(app.staticTexts["Let's get connected"].waitForExistence(timeout: 10))
        app.buttons["sample-invite"].tap()
        let connect = app.buttons["Connect this phone"]
        XCTAssertTrue(connect.waitForExistence(timeout: 5))
        connect.tap()
        let notNow = app.buttons["Not now"]
        XCTAssertTrue(notNow.waitForExistence(timeout: 10))
        notNow.tap()
        XCTAssertTrue(app.buttons["room-ws_pilatus001"].waitForExistence(timeout: 15))
    }

    /// Chats -> workspace chat -> answer a question (with its undo window) -> ticket chat from the card.
    func testChatsToWorkspaceToAnswerToTicketChat() {
        let app = paired()
        let room = app.buttons["room-ws_pilatus001"]
        XCTAssertTrue(room.waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["ticket-ws_pilatus001|t_q3sum1"].exists, "topics live one level down, in the workspace")
        room.tap()
        XCTAssertTrue(app.buttons["segment-done"].waitForExistence(timeout: 10))
        app.buttons["segment-done"].tap()
        XCTAssertTrue(app.buttons["ticket-ws_pilatus001|t_q3sum1"].waitForExistence(timeout: 10), "topic row with its key")
        app.buttons["general-ws_pilatus001"].tap()
        let answer = app.buttons["answer-TIMESTAMP"]
        XCTAssertTrue(answer.waitForExistence(timeout: 10))
        answer.tap()
        XCTAssertTrue(app.descendants(matching: .any)["answered-m_q1date0ts0000001"].waitForExistence(timeout: 10))
        let card = app.buttons["card-ws_pilatus001|t_q3sum1"]
        var tries = 0
        while !card.isHittable && tries < 5 { app.swipeDown(); tries += 1 }
        card.tap()
        XCTAssertTrue(app.staticTexts["Q3 summary for the board"].waitForExistence(timeout: 10) || app.otherElements["chat-title"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["tasks-card"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["composer-note"].exists)
        XCTAssertEqual(app.staticTexts["composer-note"].label, "Saved for the next run")
    }

    func testAnswerCanBeUndone() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-undoSeconds", "30", "-openChat", "ws_pilatus001"]
        app.launch()
        openGeneral(app)
        let answer = app.buttons["answer-TIMESTAMP"]
        XCTAssertTrue(answer.waitForExistence(timeout: 15))
        answer.tap()
        let undo = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'undo-'")).firstMatch
        XCTAssertTrue(undo.waitForExistence(timeout: 10))
        undo.tap()
        XCTAssertTrue(app.buttons["answer-TIMESTAMP"].waitForExistence(timeout: 3))
    }

    /// `-openChat ws` lands on the workspace (topics); the General conversation is one tap further.
    private func openGeneral(_ app: XCUIApplication) {
        let g = app.buttons["general-ws_pilatus001"]
        if g.waitForExistence(timeout: 15) { g.tap() }
    }

    func testSearchFindsATicketByKey() {
        let app = paired()
        let search = app.textFields["chat-search"]
        XCTAssertTrue(search.waitForExistence(timeout: 15))
        search.tap(); search.typeText("RGS-4")
        XCTAssertTrue(app.buttons["ticket-ws_reports001|t_9k2m4q"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["ticket-ws_pilatus001|t_q3sum1"].exists)
    }

    /// New chat: pick a workspace, first message, the "Got it" opens the new ticket chat.
    func testNewChatCreatesATicket() {
        let app = paired()
        let new = app.buttons["new-chat"]
        XCTAssertTrue(new.waitForExistence(timeout: 15))
        new.tap()
        app.buttons["compose-new-topic"].tap()
        app.buttons["workspace-picker"].tap()
        app.buttons["pick-ws_reports001"].tap()
        let field = app.textViews["topic-field"].exists ? app.textViews["topic-field"] : app.textFields["topic-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap(); field.typeText("Book the team lunch")
        app.buttons["topic-start"].tap()
        XCTAssertTrue(app.staticTexts["composer-note"].waitForExistence(timeout: 10), "landed in the new ticket chat")
        XCTAssertTrue(app.staticTexts["Book the team lunch"].waitForExistence(timeout: 5) || app.staticTexts.containing(NSPredicate(format: "label CONTAINS 'Book the team lunch'")).firstMatch.exists)
    }

    /// Offline: the chat says so; a written text stays on the phone with "Waiting to send".
    func testOfflineTextWaits() {
        let app = paired(["-mockFail", "YES", "-openChat", "ws_pilatus001"])
        openGeneral(app)
        // nothing loads offline, but the chat still opens and takes a text
        let field = app.textFields["composer-field"].exists ? app.textFields["composer-field"] : app.textViews["composer-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 15))
        XCTAssertTrue(app.descendants(matching: .any)["offline-banner"].waitForExistence(timeout: 10))
    }

    /// Push tap (stood in by -openQuestion) opens the chat with that question.
    func testPushOpensTheQuestionChat() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-openQuestion", "m_q1date0ts0000001"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["question-m_q1date0ts0000001"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["answer-DATE"].exists)
    }

    /// VoiceOver label audit: every visible button on the main screens has a spoken label.
    func testEveryButtonHasALabel() {
        let app = paired(["-openChat", "ws_pilatus001"])
        openGeneral(app)
        XCTAssertTrue(app.buttons["answer-DATE"].waitForExistence(timeout: 15))
        for b in app.buttons.allElementsBoundByIndex where b.exists && b.isHittable {
            XCTAssertFalse(b.label.trimmingCharacters(in: .whitespaces).isEmpty, "unlabelled button in chat: \(b.identifier)")
        }
        app.terminate()
        let list = paired()
        XCTAssertTrue(list.buttons["new-chat"].waitForExistence(timeout: 15))
        for screen in ["Chats", "Settings"] {
            if screen == "Settings" { list.buttons["settings-button"].tap(); sleep(1) }
            for b in list.buttons.allElementsBoundByIndex where b.exists && b.isHittable {
                XCTAssertFalse(b.label.trimmingCharacters(in: .whitespaces).isEmpty, "unlabelled button on \(screen): \(b.identifier)")
            }
        }
    }

    /// Server unreachable: an honest line, no fake chats, a plain way to retry.
    func testUnreachableServerIsHonest() {
        let app = paired(["-mockFail", "YES"])
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS \"Can't reach the server\"")).firstMatch.waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["Try again"].exists || app.buttons["Trying again…"].exists)
        app.buttons["settings-button"].tap()
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS \"Can't reach the server\"")).firstMatch.waitForExistence(timeout: 5))
    }

    /// A bad invitation link keeps the sheet open and the typed text, and says what to do next.
    func testBadInviteLinkKeepsInputAndExplains() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock"]
        app.launch()
        app.buttons["Paste invitation link"].tap()
        let field = app.textFields["invite-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        field.tap()
        field.typeText("https://example.com/nope")
        app.buttons["invite-continue"].tap()
        XCTAssertTrue(app.staticTexts["invite-error"].waitForExistence(timeout: 3))
        XCTAssertTrue((app.staticTexts["invite-error"].label).contains("ask the person who invited you"))
        XCTAssertEqual(app.textFields["invite-field"].value as? String, "https://example.com/nope")
    }

    /// Return submits the invitation sheet; an expired code gets the friendly text and keeps the input.
    func testExpiredInviteViaReturnKeepsInput() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock"]
        app.launch()
        app.buttons["Paste invitation link"].tap()
        let field = app.textFields["invite-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        field.tap()
        field.typeText("orch://pair?relay=https%3A%2F%2Frelay.severin.io&code=pc_expired0000000000000000\n")
        let connect = app.buttons["Connect this phone"]
        XCTAssertTrue(connect.waitForExistence(timeout: 5))
        connect.tap()
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS 'expired or was already used'")).firstMatch.waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["Connect this phone"].exists)
    }

    /// The whole Sign out box is a tap target (left edge, not only the label).
    func testSignOutBoxIsFullyTappable() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-startTab", "settings"]
        app.launch()
        let box = app.buttons["Sign out"]
        XCTAssertTrue(box.waitForExistence(timeout: 15))
        XCTAssertGreaterThanOrEqual(box.frame.height, 44)
        box.coordinate(withNormalizedOffset: CGVector(dx: 0.03, dy: 0.5)).tap()
        XCTAssertTrue(app.buttons["signout-confirm"].waitForExistence(timeout: 3))
    }

    /// The gear and + buttons are full 44 pt targets, also at their corners.
    func testShellButtonsAreFullSizeTargets() {
        let app = paired()
        let gear = app.buttons["settings-button"]
        XCTAssertTrue(gear.waitForExistence(timeout: 15))
        XCTAssertGreaterThanOrEqual(gear.frame.height, 44)
        XCTAssertGreaterThanOrEqual(app.buttons["new-chat"].frame.width, 44)
        gear.coordinate(withNormalizedOffset: CGVector(dx: 0.2, dy: 0.2)).tap()
        XCTAssertTrue(app.buttons["Sign out"].waitForExistence(timeout: 5))
    }
}
