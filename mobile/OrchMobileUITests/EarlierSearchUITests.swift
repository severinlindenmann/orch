import XCTest

/// Earlier (one Chat's past days) against MockRelay: search names its scope, a no-match line, the native clear button,
/// finished groups stay reachable, and the no-history state stays separate.
@MainActor final class EarlierSearchUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func open(_ ws: String, _ extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-open", "general:\(ws)"] + extra
        app.launch()
        let history = el(app, "chat-history")
        XCTAssertTrue(history.waitForExistence(timeout: 20), "Earlier button")
        history.tap()
        XCTAssertTrue(el(app, "history-list").waitForExistence(timeout: 10), "Earlier list")
        return app
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }
    private func days(_ app: XCUIApplication) -> XCUIElementQuery {
        app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'history-day-'"))
    }
    private func group(_ app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "identifier CONTAINS 'grp_t_cartax2026'")).firstMatch
    }
    private func search(_ app: XCUIApplication, _ text: String) {
        let field = app.searchFields.firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 5), "search field")
        field.tap()
        if let value = field.value as? String, !value.isEmpty, value != field.placeholderValue {
            field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: value.count))
        }
        field.typeText(text)
    }
    private func dayCount(_ app: XCUIApplication, _ n: Int, _ what: String) {
        let ok = NSPredicate { _, _ in self.days(app).count == n }
        XCTAssertEqual(XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: ok, object: nil)], timeout: 5), .completed,
                       "\(what): \(days(app).count) day rows, expected \(n)")
    }

    func testSearchScopeNoMatchClearAndOpenDay() throws {
        let app = open("ws_finance001", ["-mockGroups", "YES", "-mockEarlier", "YES"])
        dayCount(app, 3, "all earlier days")
        XCTAssertTrue(group(app).exists, "the finished group")
        XCTAssertEqual(app.searchFields.firstMatch.placeholderValue, "Search earlier messages in this chat")

        search(app, "invoice")
        dayCount(app, 1, "a match")
        XCTAssertTrue(group(app).exists, "groups stay while searching")

        search(app, "   ")
        dayCount(app, 3, "whitespace is no query")
        XCTAssertFalse(el(app, "history-no-match").exists)

        search(app, "car tax")   // only in the finished group's title
        dayCount(app, 0, "no match")
        let line = el(app, "history-no-match")
        XCTAssertTrue(line.waitForExistence(timeout: 5))
        XCTAssertEqual(line.label, "No earlier messages in this chat match “car tax”.")
        XCTAssertTrue(group(app).exists, "a term in a group title leaves that group reachable")
        // Audit this screen's own rows; system chrome (keyboard, glass search buttons) is Apple's.
        try app.performAccessibilityAudit(for: [.dynamicType, .sufficientElementDescription, .hitRegion, .textClipped]) { issue in
            let id = issue.element?.identifier ?? ""
            return !(id.hasPrefix("history-") || id.contains("grp_t_cartax2026"))
        }

        let field = app.searchFields.firstMatch
        field.buttons["Clear text"].tap()   // the search field's own clear button: no navigation
        dayCount(app, 3, "clearing restores the days")
        XCTAssertNotEqual(field.value as? String, "car tax")
        XCTAssertFalse(line.exists)
        XCTAssertTrue(el(app, "history-list").exists, "still on Earlier")

        days(app).firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Insurance renewal is due in December."].waitForExistence(timeout: 10), "the newest earlier day")
        app.buttons["Back to today"].firstMatch.tap()
        XCTAssertTrue(el(app, "composer-field").waitForExistence(timeout: 10), "back on today's chat")
        XCTAssertFalse(el(app, "history-list").exists)
    }

    func testNoHistoryStaysItsOwnState() {
        let app = open("ws_finance001", ["-mockGroups", "YES"])   // Finance has group messages only, no earlier Chat days
        XCTAssertTrue(app.staticTexts["Nothing here yet. Past days of this chat show up here."].waitForExistence(timeout: 5))
        search(app, "tax")
        XCTAssertTrue(app.staticTexts["Nothing here yet. Past days of this chat show up here."].exists, "no history is not a search miss")
        XCTAssertFalse(el(app, "history-no-match").exists)
    }

    /// Evidence pictures; runs only when the shots folder exists.
    func testShots() throws {
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        let dir = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/mobile-v3-messenger/build/shots/earlier-search")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: dir.path), "no shots folder")
        func shot(_ app: XCUIApplication, _ name: String) throws {
            sleep(2)
            try app.screenshot().pngRepresentation.write(to: dir.appendingPathComponent(name + ".png"))
        }
        for (size, suffix) in [("UICTContentSizeCategoryL", ""), ("UICTContentSizeCategoryAccessibilityL", "-large")] {
            let app = open("ws_finance001", ["-mockGroups", "YES", "-mockEarlier", "YES", "-UIPreferredContentSizeCategoryName", size])
            try shot(app, "loaded" + suffix)
            search(app, "car tax")
            try shot(app, "nomatch" + suffix)
            app.searchFields.firstMatch.typeText("\n")   // keyboard away: what stays on screen once you stop typing
            try shot(app, "nomatch-nokeyboard" + suffix)
            app.terminate()
        }
    }
}
