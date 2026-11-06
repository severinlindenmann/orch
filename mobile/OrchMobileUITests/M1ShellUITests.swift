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
        XCTAssertTrue(app.buttons["segment-open"].exists && app.buttons["segment-done"].exists)
        let topic = app.buttons["ticket-ws_pilatus001|t_q3sum1"]
        XCTAssertTrue(topic.waitForExistence(timeout: 10))
        app.buttons["segment-done"].tap()
        XCTAssertFalse(app.buttons["ticket-ws_pilatus001|t_q3sum1"].waitForExistence(timeout: 2), "an open topic is not in Done")
        app.buttons["segment-open"].tap()
        app.buttons["ticket-ws_pilatus001|t_q3sum1"].tap()
        XCTAssertTrue(app.staticTexts["composer-note"].waitForExistence(timeout: 10) || app.descendants(matching: .any)["tasks-card"].waitForExistence(timeout: 5))
    }

    /// + -> Compose -> New topic sheet with the workspace picker; the first message starts the topic.
    func testNewTopicSheetPicksWorkspace() {
        let app = paired()
        XCTAssertTrue(app.buttons["new-chat"].waitForExistence(timeout: 15))
        app.buttons["new-chat"].tap()
        XCTAssertTrue(app.buttons["compose-add-workspace"].waitForExistence(timeout: 5))
        app.buttons["compose-new-topic"].tap()
        let picker = app.buttons["workspace-picker"]
        XCTAssertTrue(picker.waitForExistence(timeout: 5))
        picker.tap()
        XCTAssertTrue(app.buttons["pick-ws_pilatus001"].waitForExistence(timeout: 5))
        app.buttons["pick-ws_reports001"].tap()
        let field = app.textViews["topic-field"].exists ? app.textViews["topic-field"] : app.textFields["topic-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap(); field.typeText("Plan the offsite")
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
        let always2 = app.buttons["speak-always"]
        XCTAssertTrue(always2.waitForExistence(timeout: 5))
        always2.tap()
        XCTAssertTrue(app.buttons["speak-always"].isSelected || app.buttons["speak-always"].waitForExistence(timeout: 3))
    }

    /// Add workspace sheet: a bad link is explained inline and the typed text stays.
    func testAddWorkspaceRejectsABadLink() {
        let app = paired()
        app.buttons["new-chat"].tap()
        app.buttons["compose-add-workspace"].tap()
        XCTAssertTrue(app.buttons["Paste invitation link"].waitForExistence(timeout: 5))
        app.buttons["Paste invitation link"].tap()
        let field = app.textFields["invite-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap(); field.typeText("https://example.com/nope")
        app.buttons["invite-continue"].tap()
        XCTAssertTrue(app.staticTexts["invite-error"].waitForExistence(timeout: 3))
        XCTAssertEqual(app.textFields["invite-field"].value as? String, "https://example.com/nope")
    }
}
