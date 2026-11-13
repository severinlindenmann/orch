import XCTest

final class GroupRoomScrollUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    @MainActor private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any)[id].firstMatch
    }

    @MainActor private func waitUntilHittable(_ element: XCUIElement, timeout: TimeInterval = 10,
                                             file: StaticString = #filePath, line: UInt = #line) {
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == true AND hittable == true"), object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: timeout), .completed, file: file, line: line)
    }

    @MainActor private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES",
                                "-mockGroups", "YES", "-mockLongGroup", "YES"]
        app.launch()
        XCTAssertTrue(element(app, "chat-search").waitForExistence(timeout: 15))
        return app
    }

    @MainActor private func revealInList(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        let row = element(app, id)
        for _ in 0..<10 where !(row.exists && row.isHittable) { app.swipeUp() }
        waitUntilHittable(row)
        return row
    }

    @MainActor func testOpensAtNewestMessageAndScrollsAfterSending() {
        let app = launch()
        revealInList(app, "group-13-ws_finance001-grp_t_cartax2027").tap()
        XCTAssertTrue(element(app, "group-members").waitForExistence(timeout: 10))
        // No transcript swipe: a long room opens at its open approval card (P28), whole and above the composer;
        // "Jump to latest" then reaches the newest message.
        let card = element(app, "group-approval")
        waitUntilHittable(card.buttons["Allow once"])
        // The whole footer (thinking line, To: line, field): the card was first clipped by the To: line.
        XCTAssertLessThanOrEqual(card.frame.maxY, element(app, "group-composer").frame.minY, "card not behind the composer")
        let jump = element(app, "jump-latest")
        waitUntilHittable(jump)
        // Messages below the card were not seen yet: opening at the card must not mark them read (P55).
        XCTAssertTrue(jump.label.contains("unread"), "jump button keeps the unread count: \(jump.label)")
        jump.tap()
        waitUntilHittable(app.staticTexts["Group scroll message 25"])
        let field = element(app, "composer-field")
        waitUntilHittable(field)
        field.tap()
        let text = "Phone group scroll reply"
        field.typeText(text)
        let send = element(app, "composer-send")
        waitUntilHittable(send)
        send.tap()
        let sent = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
        if !sent.waitForExistence(timeout: 10) { XCTFail("sent text missing; field value: \(String(describing: field.value))\n" + app.debugDescription) }
        waitUntilHittable(sent)
    }

    /// "Open the Finance topic" in the info sheet pushes the topic once the sheet has closed; Back returns to the room.
    @MainActor private func openTopicFromInfo(_ app: XCUIApplication) {
        element(app, "group-members").tap()
        let link = element(app, "group-open-topic")
        waitUntilHittable(link)
        link.tap()
        XCTAssertTrue(element(app, "chat-title").waitForExistence(timeout: 10), "topic opened")
        element(app, "chat-back").tap()
        XCTAssertTrue(element(app, "group-members").waitForExistence(timeout: 10), "back in the group room")
    }

    @MainActor func testOpenTopicFromGroupInfoInChatsAndHistory() {
        let app = launch()
        revealInList(app, "group-13-ws_finance001-grp_t_cartax2027").tap()
        XCTAssertTrue(element(app, "group-members").waitForExistence(timeout: 10))
        openTopicFromInfo(app)
        element(app, "group-back").tap()
        revealInList(app, "group-history").tap()
        let row = element(app, "group-13-ws_finance001-grp_t_cartax2026")
        waitUntilHittable(row)
        row.tap()
        XCTAssertTrue(element(app, "group-members").waitForExistence(timeout: 10))
        openTopicFromInfo(app)
    }

    @MainActor func testDoneGroupOpensFromHistoryReadOnly() {
        let app = launch()
        revealInList(app, "group-history").tap()
        let row = element(app, "group-13-ws_finance001-grp_t_cartax2026")
        waitUntilHittable(row)
        row.tap()
        XCTAssertTrue(element(app, "group-members").waitForExistence(timeout: 10))
        waitUntilHittable(app.staticTexts["Read only"])
        XCTAssertFalse(element(app, "composer").exists)
    }
}
