import XCTest

/// Lane M1 flows against the in-process MockRelay: workspace -> topics, new topic sheet, settings, add workspace, mute, voice.
final class M1ShellUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func paired(_ extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-undoSeconds", "1"] + extra
        app.launch()
        return app
    }

    /// Chats -> workspace: General row, Open/Done segments, the topic opens its conversation.
    func testWorkspaceShowsGeneralAndTopics() {
        let app = paired()
        let room = app.buttons["room-ws_pilatus001"]
        XCTAssertTrue(room.waitForExistence(timeout: 15))
        room.tap()
        XCTAssertTrue(app.buttons["general-ws_pilatus001"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["done-toggle"].exists)
        // t_q3sum1 has its result already: it lives under the collapsed Done group.
        XCTAssertFalse(app.buttons["ticket-ws_pilatus001|t_q3sum1"].waitForExistence(timeout: 2), "a finished topic is collapsed under Done")
        app.buttons["done-toggle"].tap()
        let topic = app.buttons["ticket-ws_pilatus001|t_q3sum1"]
        XCTAssertTrue(topic.waitForExistence(timeout: 10))
        app.reveal(topic)
        topic.tap()
        XCTAssertTrue(app.staticTexts["composer-note"].waitForExistence(timeout: 10) || app.descendants(matching: .any)["tasks-card"].waitForExistence(timeout: 5))
    }

    /// A working topic is listed under Open.
    func testWorkingTopicIsOpen() {
        let app = paired()
        let room = app.buttons["room-ws_reports001"]
        XCTAssertTrue(room.waitForExistence(timeout: 15))
        room.tap()
        XCTAssertTrue(app.buttons["ticket-ws_reports001|t_9k2m4q"].waitForExistence(timeout: 10))
    }

    /// + -> New chat -> New topic sheet with the workspace picker; the first message starts the topic.
    func testNewTopicSheetPicksWorkspace() {
        let app = paired()
        XCTAssertTrue(app.buttons["new-chat"].waitForExistence(timeout: 15))
        app.buttons["new-chat"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["new-chat-sheet"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["compose-add-workspace"].waitForExistence(timeout: 5))
        app.buttons["compose-new-topic"].tap()
        let picker = app.buttons["workspace-picker"]
        XCTAssertTrue(picker.waitForExistence(timeout: 10))
        picker.tap()
        XCTAssertTrue(app.buttons["pick-ws_pilatus001"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["pick-ws_reports001"].waitForExistence(timeout: 10))
        app.buttons["pick-ws_reports001"].tap()
        let field = app.textViews["topic-field"].exists ? app.textViews["topic-field"] : app.textFields["topic-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap(); expectKeyboardFocus(field); field.typeText("Plan the offsite")
        app.buttons["topic-start"].tap()
        XCTAssertTrue(app.staticTexts["composer-note"].waitForExistence(timeout: 10), "landed in the new topic")
    }

    /// Settings: workspace list, mute a workspace, voice defaults.
    func testSettingsMuteAndVoice() {
        let app = paired()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        let ws = app.buttons["settings-ws-ws_pilatus001"]
        XCTAssertTrue(ws.waitForExistence(timeout: 10))
        ws.tap()
        let always = app.buttons["mute-Always"]
        XCTAssertTrue(always.waitForExistence(timeout: 5))
        always.tap()
        XCTAssertTrue(app.buttons["mute-Always"].waitForExistence(timeout: 5))
        app.navigationBars.buttons.element(boundBy: 0).tap()
        let voice = app.buttons["voice-settings"]
        var tries = 0
        while !voice.isHittable && tries < 4 { app.swipeUp(); tries += 1 }
        voice.tap()
        app.buttons["voice-replies-menu"].tap()
        let always2 = app.buttons["speak-always"]
        XCTAssertTrue(always2.waitForExistence(timeout: 5))
        always2.tap()
        XCTAssertTrue(app.buttons["voice-replies-menu"].exists)
    }

    /// Add workspace sheet: a bad link is explained inline and the typed text stays.
    func testAddWorkspaceRejectsABadLink() {
        let app = paired()
        XCTAssertTrue(app.buttons["new-chat"].waitForExistence(timeout: 15))
        app.buttons["new-chat"].tap()
        XCTAssertTrue(app.buttons["compose-add-workspace"].waitForExistence(timeout: 5))
        app.buttons["compose-add-workspace"].tap()
        if app.buttons["Use invitation"].exists { app.buttons["Use invitation"].tap() }
        XCTAssertTrue(app.buttons["Paste invitation link"].waitForExistence(timeout: 5))
        app.buttons["Paste invitation link"].tap()
        let field = app.textFields["invite-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap(); field.typeText("https://example.com/nope")
        app.buttons["invite-continue"].tap()
        XCTAssertTrue(app.staticTexts["invite-error"].waitForExistence(timeout: 3))
        XCTAssertEqual(app.textFields["invite-field"].value as? String, "https://example.com/nope")
    }

    /// Add workspace from Settings: a used invitation is explained, the next good one clears that message and "Open" lands on the new workspace.
    func testAddWorkspaceFromSettingsThenOpenIt() {
        let app = paired()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(app.buttons["add-workspace"].waitForExistence(timeout: 10))
        app.buttons["add-workspace"].tap()
        func enter(_ link: String) {
            if app.buttons["Use invitation"].exists { app.buttons["Use invitation"].tap() }
            XCTAssertTrue(app.buttons["Paste invitation link"].waitForExistence(timeout: 5))
            app.buttons["Paste invitation link"].tap()
            let field = app.textFields["invite-field"]
            XCTAssertTrue(field.waitForExistence(timeout: 5))
            field.tap(); field.typeText(link)
            app.buttons["invite-continue"].tap()
        }
        enter("orch://pair?relay=https%3A%2F%2Frelay.severin.io&code=pc_expiredAAAAAAAAAAAAAA")
        XCTAssertTrue(app.buttons["invite-add"].waitForExistence(timeout: 5)); app.buttons["invite-add"].tap()
        XCTAssertTrue(app.staticTexts["invite-error"].waitForExistence(timeout: 10), "the used invitation is explained")
        app.buttons["Try another link"].tap()
        enter("orch://pair?relay=https%3A%2F%2Frelay.severin.io&code=pc_Tg5Yh7Uj9Ik2Ol4Pz6Xc8V")
        XCTAssertTrue(app.buttons["invite-add"].waitForExistence(timeout: 5)); app.buttons["invite-add"].tap()
        let open = app.buttons["Open Home"]
        XCTAssertTrue(open.waitForExistence(timeout: 10), "added")
        XCTAssertFalse(app.staticTexts["invite-error"].exists, "the old error is gone")
        open.tap()
        XCTAssertTrue(app.buttons["general-ws_home000001"].waitForExistence(timeout: 10), "the new workspace opens")
    }

    /// Screenshots for the PR (default and XXL text) when the shots folder exists.
    func testShots() throws {
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        let out = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/mobile-v3-messenger/build/shots/m1")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: out.path), "no shots folder")
        for (suffix, size) in [("", nil), ("-xxl", "UICTContentSizeCategoryXXL")] as [(String, String?)] {
            var extra: [String] = size.map { ["-UIPreferredContentSizeCategoryName", $0] } ?? []
            func snap(_ app: XCUIApplication, _ name: String) throws {
                sleep(2); try app.screenshot().pngRepresentation.write(to: out.appendingPathComponent("app-\(name)\(suffix).png"))
            }
            var app = paired(extra)
            XCTAssertTrue(app.buttons["room-ws_pilatus001"].waitForExistence(timeout: 15)); try snap(app, "1-chats")
            app.buttons["room-ws_pilatus001"].tap(); XCTAssertTrue(app.buttons["done-toggle"].waitForExistence(timeout: 10)); try snap(app, "2-workspace-open")
            app.buttons["done-toggle"].tap(); try snap(app, "3-workspace-done")
            app.terminate()
            app = paired(extra + ["-startTab", "settings"])
            XCTAssertTrue(app.buttons["Sign out"].waitForExistence(timeout: 15)); try snap(app, "4-settings")
            app.buttons["voice-settings"].tap(); XCTAssertTrue(app.buttons["voice-replies-menu"].waitForExistence(timeout: 5)); try snap(app, "5-voice")
            app.terminate()
            app = paired(extra)
            app.buttons["new-chat"].tap(); XCTAssertTrue(app.buttons["compose-new-topic"].waitForExistence(timeout: 5)); try snap(app, "6-compose")
            app.buttons["compose-new-topic"].tap(); XCTAssertTrue(app.buttons["workspace-picker"].waitForExistence(timeout: 5)); try snap(app, "7-new-topic")
            app.terminate(); extra = extra + []
            app = paired(extra)
            app.buttons["new-chat"].tap(); app.buttons["compose-add-workspace"].tap()
            if app.buttons["Use invitation"].exists { app.buttons["Use invitation"].tap() }
            XCTAssertTrue(app.buttons["Paste invitation link"].waitForExistence(timeout: 5)); try snap(app, "8-add-workspace")
            app.terminate()
        }
    }
}

extension XCTestCase {
    /// Waits (event based, no sleep) until the tapped field really holds keyboard focus; typing before that is dropped on slow runners.
    func expectKeyboardFocus(_ field: XCUIElement, timeout: TimeInterval = 10) {
        let focused = NSPredicate(format: "hasKeyboardFocus == true")
        let e = XCTNSPredicateExpectation(predicate: focused, object: field)
        if XCTWaiter.wait(for: [e], timeout: timeout) != .completed { field.tap() }
    }
}
